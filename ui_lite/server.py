from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Set, Tuple

import redis
from websockets.datastructures import Headers
from websockets.legacy.server import WebSocketServerProtocol, serve

from config.config import Config, load_config
from core.env_loader import load_env
from core.validation.validator import ContractError, SchemaValidator

log = logging.getLogger("ui_lite")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


@dataclass
class UiLiteHandle:
    thread: threading.Thread
    stop_event: threading.Event

    def stop(self) -> None:
        self.stop_event.set()
        try:
            self.thread.join(timeout=2.0)
        except KeyboardInterrupt:
            print("Отримано KeyboardInterrupt. UI Lite завершено примусово")
            return


class DedupIndex:
    def __init__(self) -> None:
        self._seen: Set[Tuple[str, str, int]] = set()

    def add_if_new(self, symbol: str, tf: str, open_time: int) -> bool:
        key = (symbol, tf, open_time)
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


def build_dedup_key(payload: Dict[str, Any], bar: Dict[str, Any]) -> Optional[Tuple[str, str, int]]:
    symbol = str(payload.get("symbol", ""))
    tf = str(payload.get("tf", ""))
    open_time = bar.get("open_time")
    if open_time is None:
        open_time = bar.get("open_time_ms")
    if not symbol or not tf or open_time is None:
        return None
    return (symbol, tf, int(open_time))


def is_final_bar(payload: Dict[str, Any], bar: Dict[str, Any]) -> bool:
    complete = bar.get("complete")
    if complete is None:
        complete = payload.get("complete", False)
    return bool(complete is True)


def is_preview_bar(payload: Dict[str, Any], bar: Dict[str, Any]) -> bool:
    return not is_final_bar(payload, bar)


HTTPResponse = Any


@dataclass
class UiLiteState:
    lock: threading.Lock
    subscribed_channel: str
    redis_rx_total: int = 0
    redis_json_err_total: int = 0
    redis_contract_err_total: int = 0
    ws_tx_total: int = 0
    ws_clients: int = 0
    last_error_code: str = ""
    last_error_message: str = ""
    last_payload_symbol: str = ""
    last_payload_tf: str = ""
    last_payload_ts_ms: int = 0
    last_payload_open_time_ms: int = 0
    last_payload_close_time_ms: int = 0
    last_payload_mode: str = ""
    last_ui_bar_time_s: int = 0
    last_ring_key: str = ""
    last_ring_size: int = 0
    last_status_snapshot: Dict[str, Any] = field(default_factory=dict)
    last_status_ts_ms: int = 0
    ohlcv_inbound_invalid_total: int = 0
    ohlcv_inbound_last_error: str = ""
    status_invalid_total: int = 0
    status_last_error: str = ""
    status_ok: bool = False
    status_last_error_short: str = ""

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "subscribed_channel": self.subscribed_channel,
                "redis_rx_total": self.redis_rx_total,
                "redis_json_err_total": self.redis_json_err_total,
                "redis_contract_err_total": self.redis_contract_err_total,
                "ws_tx_total": self.ws_tx_total,
                "ws_clients": self.ws_clients,
                "last_error_code": self.last_error_code,
                "last_error_message": self.last_error_message,
                "last_payload_symbol": self.last_payload_symbol,
                "last_payload_tf": self.last_payload_tf,
                "last_payload_ts_ms": self.last_payload_ts_ms,
                "last_payload_open_time_ms": self.last_payload_open_time_ms,
                "last_payload_close_time_ms": self.last_payload_close_time_ms,
                "last_payload_mode": self.last_payload_mode,
                "last_ui_bar_time_s": self.last_ui_bar_time_s,
                "last_ring_key": self.last_ring_key,
                "last_ring_size": self.last_ring_size,
                "last_status_snapshot": self.last_status_snapshot or {},
                "last_status_ts_ms": self.last_status_ts_ms,
                "ohlcv_inbound_invalid_total": self.ohlcv_inbound_invalid_total,
                "ohlcv_inbound_last_error": self.ohlcv_inbound_last_error,
                "status_invalid_total": self.status_invalid_total,
                "status_last_error": self.status_last_error,
                "status_ok": self.status_ok,
                "status_last_error_short": self.status_last_error_short,
            }


_STATE = UiLiteState(lock=threading.Lock(), subscribed_channel="")
_RING_BUFFERS: Dict[Tuple[str, str, str], Deque[Tuple[int, Dict[str, Any]]]] = {}
_DEDUP_KEYS: Dict[Tuple[str, str, str], Set[int]] = {}


def _make_headers(content_type: str, length: int) -> Headers:
    headers = Headers()
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(length)
    headers["Connection"] = "close"
    return headers


def _process_request(path: str, _headers: Any) -> Optional[HTTPResponse]:
    try:
        upgrade = ""
        if hasattr(_headers, "get"):
            upgrade = _headers.get("Upgrade") or _headers.get("upgrade") or ""
        if isinstance(upgrade, bytes):
            upgrade = upgrade.decode("utf-8")
        if str(upgrade).lower() == "websocket":
            return None
        static_dir = Path(__file__).resolve().parent / "static"
        if path == "/debug":
            payload = json.dumps(_STATE.snapshot(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            return HTTPStatus.OK, _make_headers("application/json; charset=utf-8", len(payload)), payload
        if path in ("/", "/index.html"):
            file_path = static_dir / "index.html"
            response = _read_file(file_path, "text/html; charset=utf-8")
            print(f"UI Lite HTTP {path} -> {response[0]}", file=sys.stderr, flush=True)
            return response
        if path == "/app.js":
            file_path = static_dir / "app.js"
            response = _read_file(file_path, "application/javascript; charset=utf-8")
            print(f"UI Lite HTTP {path} -> {response[0]}", file=sys.stderr, flush=True)
            return response
        if path == "/chart_adapter.js":
            file_path = static_dir / "chart_adapter.js"
            response = _read_file(file_path, "application/javascript; charset=utf-8")
            print(f"UI Lite HTTP {path} -> {response[0]}", file=sys.stderr, flush=True)
            return response
        if path == "/styles.css":
            file_path = static_dir / "styles.css"
            response = _read_file(file_path, "text/css; charset=utf-8")
            print(f"UI Lite HTTP {path} -> {response[0]}", file=sys.stderr, flush=True)
            return response
        if path == "/vendor/lightweight-charts.standalone.production.js":
            file_path = static_dir / "vendor" / "lightweight-charts.standalone.production.js"
            response = _read_file(file_path, "application/javascript; charset=utf-8")
            print(f"UI Lite HTTP {path} -> {response[0]}", file=sys.stderr, flush=True)
            return response
        if path == "/favicon.ico":
            response = (
                HTTPStatus.NO_CONTENT,
                _make_headers("image/x-icon", 0),
                b"",
            )
            print(f"UI Lite HTTP {path} -> {response[0]}", file=sys.stderr, flush=True)
            return response
        body = b"not found"
        response = (
            HTTPStatus.NOT_FOUND,
            _make_headers("text/plain; charset=utf-8", len(body)),
            body,
        )
        print(f"UI Lite HTTP {path} -> {response[0]}", file=sys.stderr, flush=True)
        return response
    except Exception as exc:
        msg = f"process_request error: {exc}".encode("utf-8")
        headers = _make_headers("text/plain; charset=utf-8", len(msg))
        print(f"UI Lite HTTP {path} -> 500", file=sys.stderr, flush=True)
        return HTTPStatus.INTERNAL_SERVER_ERROR, headers, msg


def _mode_from_payload(payload: Dict[str, Any], bar: Dict[str, Any]) -> str:
    complete = bar.get("complete")
    if complete is None:
        complete = payload.get("complete", False)
    return "final" if bool(complete is True) else "preview"


def _normalize_bar(payload: Dict[str, Any], bar: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    open_time = bar.get("open_time")
    if open_time is None:
        open_time = bar.get("open_time_ms")
    if open_time is None:
        return None
    open_time_ms = int(open_time)
    time_s = int(open_time_ms / 1000)
    if time_s <= 0:
        return None
    out = {
        "time": time_s,
        "open": float(bar.get("open", 0.0)),
        "high": float(bar.get("high", 0.0)),
        "low": float(bar.get("low", 0.0)),
        "close": float(bar.get("close", 0.0)),
    }
    if "volume" in bar:
        out["volume"] = float(bar.get("volume", 0.0))
    return out


def _buffer_bar(symbol: str, tf: str, mode: str, bar: Dict[str, Any], open_time_ms: int) -> bool:
    key = (symbol, tf, mode)
    ring = _RING_BUFFERS.get(key)
    if ring is None:
        ring = deque(maxlen=3000)
        _RING_BUFFERS[key] = ring
    dedup = _DEDUP_KEYS.get(key)
    if dedup is None:
        dedup = set()
        _DEDUP_KEYS[key] = dedup
    if open_time_ms in dedup:
        for idx, (open_ms, _prev) in enumerate(ring):
            if int(open_ms) == int(open_time_ms):
                ring[idx] = (open_time_ms, bar)
                with _STATE.lock:
                    _STATE.last_ui_bar_time_s = int(bar.get("time", 0))
                    _STATE.last_ring_key = f"{symbol}:{tf}:{mode}"
                    _STATE.last_ring_size = len(ring)
                return True
        return False
    maxlen = ring.maxlen
    if maxlen is not None and len(ring) >= maxlen:
        old_open_ms, _ = ring.popleft()
        dedup.discard(int(old_open_ms))
    ring.append((open_time_ms, bar))
    dedup.add(open_time_ms)
    with _STATE.lock:
        _STATE.last_ui_bar_time_s = int(bar.get("time", 0))
        _STATE.last_ring_key = f"{symbol}:{tf}:{mode}"
        _STATE.last_ring_size = len(ring)
    return True


def _snapshot_for(symbol: str, tf: str, mode: str) -> list:
    ring = _RING_BUFFERS.get((symbol, tf, mode))
    if ring is None:
        return []
    return [bar for _open_ms, bar in list(ring)]


def _read_file(path: Path, content_type: str) -> HTTPResponse:
    try:
        body = path.read_bytes()
    except FileNotFoundError:
        body = b"not found"
        headers = _make_headers("text/plain; charset=utf-8", len(body))
        return HTTPStatus.NOT_FOUND, headers, body
    headers = _make_headers(content_type, len(body))
    return HTTPStatus.OK, headers, body


def _update_ws_clients(clients: Set[WebSocketServerProtocol]) -> None:
    with _STATE.lock:
        _STATE.ws_clients = len(clients)


def _subscribe_error(code: str, message: str) -> Dict[str, Any]:
    return {"type": "error", "code": code, "message": message}


def _parse_subscribe(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], str, Optional[Dict[str, Any]]]:
    if payload.get("type") != "subscribe":
        return None, None, "preview", None
    symbol = payload.get("symbol")
    tf = payload.get("tf")
    mode = payload.get("mode", "preview")
    if not symbol:
        return (
            None,
            None,
            str(mode or "preview"),
            _subscribe_error(
                "missing_symbol",
                "UI Lite subscribe вимагає symbol",
            ),
        )
    if not tf:
        return (
            None,
            None,
            str(mode or "preview"),
            _subscribe_error(
                "missing_tf",
                "UI Lite subscribe вимагає tf",
            ),
        )
    return str(symbol), str(tf), str(mode or "preview"), None


async def _ws_handler(
    websocket: WebSocketServerProtocol,
    clients: Set[WebSocketServerProtocol],
    subs: Dict[WebSocketServerProtocol, Dict[str, Any]],
) -> None:
    clients.add(websocket)
    subs[websocket] = {"symbol": None, "tf": None, "mode": "preview"}
    _update_ws_clients(clients)
    try:
        async for message in websocket:
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                continue
            if payload.get("type") != "subscribe":
                continue
            symbol, tf, mode, error_payload = _parse_subscribe(payload)
            if error_payload is not None:
                await websocket.send(json.dumps(error_payload, ensure_ascii=False, separators=(",", ":")))
                with _STATE.lock:
                    _STATE.ws_tx_total += 1
                continue
            subs[websocket] = {"symbol": symbol, "tf": tf, "mode": mode}
            log.debug("UI Lite WS subscribe: symbol=%s tf=%s mode=%s", symbol, tf, mode)

            snapshot = _snapshot_for(str(symbol), str(tf), str(mode or "preview"))
            response = {
                "type": "snapshot",
                "symbol": symbol,
                "tf": tf,
                "mode": mode,
                "bars": snapshot,
            }
            await websocket.send(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
            with _STATE.lock:
                _STATE.ws_tx_total += 1
    finally:
        clients.discard(websocket)
        subs.pop(websocket, None)
        _update_ws_clients(clients)


def _start_redis_subscriber(
    redis_client: redis.Redis,
    channel: str,
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
    stop_event: threading.Event,
    validator: SchemaValidator,
    max_bars_per_message: int,
) -> threading.Thread:
    def _run() -> None:
        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(channel)
        log.debug("UI Lite Redis subscribe: channel=%s", channel)
        while not stop_event.is_set():
            message = pubsub.get_message(timeout=1.0)
            if not message:
                continue
            with _STATE.lock:
                _STATE.redis_rx_total += 1
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if isinstance(data, bytes):
                raw = data.decode("utf-8")
            else:
                raw = str(data)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                with _STATE.lock:
                    _STATE.redis_json_err_total += 1
                continue
            try:
                validator.validate_ohlcv_v1(payload, max_bars_per_message)
            except ContractError as exc:
                with _STATE.lock:
                    _STATE.redis_contract_err_total += 1
                    _STATE.last_error_code = "ohlcv_contract_error"
                    _STATE.last_error_message = str(exc)
                    _STATE.ohlcv_inbound_invalid_total += 1
                    _STATE.ohlcv_inbound_last_error = str(exc)
                continue
            with _STATE.lock:
                _STATE.last_payload_symbol = str(payload.get("symbol", ""))
                _STATE.last_payload_tf = str(payload.get("tf", ""))
                ts_val = int(payload.get("ts", 0))
                if ts_val > 0:
                    _STATE.last_payload_ts_ms = ts_val
            if loop.is_closed():
                break
            try:
                asyncio.run_coroutine_threadsafe(queue.put(payload), loop)
            except RuntimeError:
                break
        try:
            pubsub.close()
        except Exception:
            pass

    thread = threading.Thread(target=_run, name="ui_lite_redis", daemon=True)
    thread.start()
    return thread


def _start_status_poller(
    redis_client: redis.Redis,
    status_key: str,
    stop_event: threading.Event,
    validator: SchemaValidator,
) -> threading.Thread:
    def _run() -> None:
        log.debug("UI Lite status poller: key=%s", status_key)
        while not stop_event.is_set():
            try:
                raw = redis_client.get(status_key)
            except Exception as exc:  # noqa: BLE001
                log.error("UI Lite status poller: помилка Redis: %s", exc)
                time.sleep(1.0)
                continue
            if not raw:
                with _STATE.lock:
                    _STATE.status_ok = False
                    _STATE.status_last_error_short = "status_missing"
                time.sleep(1.0)
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                with _STATE.lock:
                    _STATE.status_invalid_total += 1
                    _STATE.status_last_error = f"json_error: {exc}"
                    _STATE.status_ok = False
                    _STATE.status_last_error_short = "json_error"
                time.sleep(1.0)
                continue
            try:
                validator.validate_status_v2(payload)
            except ContractError as exc:
                with _STATE.lock:
                    _STATE.status_invalid_total += 1
                    _STATE.status_last_error = str(exc)
                    _STATE.status_ok = False
                    _STATE.status_last_error_short = str(exc)[:120]
                time.sleep(1.0)
                continue
            ts_ms = int(payload.get("ts_ms") or payload.get("ts") or int(time.time() * 1000))
            with _STATE.lock:
                _STATE.last_status_snapshot = dict(payload)
                _STATE.last_status_ts_ms = ts_ms
                _STATE.status_ok = True
                _STATE.status_last_error_short = ""
            time.sleep(1.0)

    thread = threading.Thread(target=_run, name="ui_lite_status", daemon=True)
    thread.start()
    return thread


async def _broadcaster(
    queue: asyncio.Queue,
    clients: Set[WebSocketServerProtocol],
    dedup: DedupIndex,
    subs: Dict[WebSocketServerProtocol, Dict[str, Any]],
) -> None:
    state_cache: Dict[Tuple[str, str, int], Tuple[float, float, float, float, bool]] = {}
    while True:
        payload = await queue.get()
        bars = payload.get("bars", [])
        if not isinstance(bars, list):
            continue
        symbol = str(payload.get("symbol", ""))
        tf = str(payload.get("tf", ""))
        bars_sorted = sorted(
            bars,
            key=lambda bar: int(bar.get("open_time", bar.get("open_time_ms", 0)) or 0),
        )
        filtered = []
        for bar in bars_sorted:
            key = build_dedup_key(payload, bar)
            if key is None:
                continue
            _, _, open_time = key
            open_val = float(bar.get("open", 0.0))
            high_val = float(bar.get("high", 0.0))
            low_val = float(bar.get("low", 0.0))
            close_val = float(bar.get("close", 0.0))
            complete_val = bool(
                bar.get("complete") if bar.get("complete") is not None else payload.get("complete", False)
            )
            state = (open_val, high_val, low_val, close_val, complete_val)
            prev_state = state_cache.get(key)
            state_cache[key] = state
            is_new = dedup.add_if_new(symbol, tf, open_time)
            if not is_new and prev_state == state:
                continue
            filtered.append(bar)
        if not filtered:
            continue
        for bar in filtered:
            mode = _mode_from_payload(payload, bar)
            norm = _normalize_bar(payload, bar)
            if norm is None:
                continue
            open_time_ms = int(bar.get("open_time", bar.get("open_time_ms", 0)))
            if not _buffer_bar(symbol, tf, mode, norm, open_time_ms):
                continue
            with _STATE.lock:
                _STATE.last_payload_open_time_ms = int(bar.get("open_time", bar.get("open_time_ms", 0)))
                _STATE.last_payload_close_time_ms = int(bar.get("close_time", bar.get("close_time_ms", 0)))
                _STATE.last_payload_mode = mode
                if _STATE.last_payload_ts_ms == 0:
                    _STATE.last_payload_ts_ms = int(payload.get("ts", 0))
                if _STATE.last_payload_ts_ms == 0:
                    _STATE.last_payload_ts_ms = int(open_time_ms)
            out = {"type": "bar", "symbol": symbol, "tf": tf, "mode": mode, "bar": norm}
            data = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
            for ws in list(clients):
                sub = subs.get(ws, {})
                if sub.get("symbol") and sub.get("symbol") != symbol:
                    continue
                if sub.get("tf") and sub.get("tf") != tf:
                    continue
                if sub.get("mode") and sub.get("mode") != mode:
                    continue
                try:
                    await ws.send(data)
                    with _STATE.lock:
                        _STATE.ws_tx_total += 1
                except Exception:
                    clients.discard(ws)
                    subs.pop(ws, None)
                    _update_ws_clients(clients)


def _build_health_payload(now_ms: int) -> Dict[str, Any]:
    with _STATE.lock:
        status_payload = dict(_STATE.last_status_snapshot) if _STATE.last_status_snapshot else {}
        status_ok = bool(_STATE.status_ok)
        last_status_ts_ms = int(_STATE.last_status_ts_ms)
        status_age_ms = int(now_ms - last_status_ts_ms) if status_ok and last_status_ts_ms > 0 else None
        status_stale = bool(status_age_ms is not None and status_age_ms > 5000)
        ui_payload = {
            "ohlcv_inbound_invalid_total": _STATE.ohlcv_inbound_invalid_total,
            "ohlcv_inbound_last_error": _STATE.ohlcv_inbound_last_error,
            "status_invalid_total": _STATE.status_invalid_total,
            "status_last_error": _STATE.status_last_error,
        }
        last_status_error_short = _STATE.status_last_error_short or ""
    return {
        "type": "health",
        "ts": int(now_ms),
        "status": status_payload,
        "ui": ui_payload,
        "status_ok": status_ok,
        "status_age_ms": status_age_ms,
        "status_stale": status_stale,
        "last_status_error_short": last_status_error_short,
    }


async def _health_broadcaster(
    stop_event: threading.Event,
    clients: Set[WebSocketServerProtocol],
) -> None:
    while not stop_event.is_set():
        await asyncio.sleep(1.0)
        payload = _build_health_payload(int(time.time() * 1000))
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        for ws in list(clients):
            try:
                await ws.send(data)
                with _STATE.lock:
                    _STATE.ws_tx_total += 1
            except Exception:
                clients.discard(ws)


async def _log_state(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        await asyncio.sleep(5.0)
        snap = _STATE.snapshot()
        print(
            "UI Lite stats: rx={redis_rx_total} json_err={redis_json_err_total} "
            "clients={ws_clients} last={last_payload_symbol}/{last_payload_tf} ts={last_payload_ts_ms}".format(**snap),
            file=sys.stderr,
            flush=True,
        )


async def _run_server(config: Config, redis_client: redis.Redis, stop_event: threading.Event) -> None:
    clients: Set[WebSocketServerProtocol] = set()
    queue: asyncio.Queue = asyncio.Queue()
    dedup = DedupIndex()
    subs: Dict[WebSocketServerProtocol, Dict[str, Any]] = {}
    loop = asyncio.get_running_loop()
    validator = SchemaValidator(root_dir=Path(__file__).resolve().parents[1])
    with _STATE.lock:
        _STATE.subscribed_channel = config.ch_ohlcv()
    log.debug("UI Lite startup: redis_channel=%s", config.ch_ohlcv())
    _start_redis_subscriber(
        redis_client,
        config.ch_ohlcv(),
        loop,
        queue,
        stop_event,
        validator,
        int(config.max_bars_per_message),
    )
    _start_status_poller(
        redis_client=redis_client,
        status_key=config.key_status_snapshot(),
        stop_event=stop_event,
        validator=validator,
    )

    def _is_port_in_use_error(exc: OSError) -> bool:
        return getattr(exc, "errno", None) == 10048 or getattr(exc, "winerror", None) == 10048

    while not stop_event.is_set():
        try:
            async with serve(
                lambda ws, _path: _ws_handler(ws, clients, subs),
                host=config.ui_lite_host,
                port=config.ui_lite_port,
                process_request=_process_request,  # type: ignore[arg-type]
            ):
                print(
                    f"UI Lite слухає http://{config.ui_lite_host}:{config.ui_lite_port}",
                    file=sys.stderr,
                    flush=True,
                )
                broadcaster_task = asyncio.create_task(_broadcaster(queue, clients, dedup, subs))
                health_task = asyncio.create_task(_health_broadcaster(stop_event, clients))
                log_task = asyncio.create_task(_log_state(stop_event))

                def _on_broadcaster_done(task: asyncio.Task) -> None:
                    if task.cancelled():
                        return
                    exc = task.exception()
                    if exc is not None:
                        print(f"UI Lite broadcaster error: {exc}", file=sys.stderr)

                broadcaster_task.add_done_callback(_on_broadcaster_done)
                try:
                    await _stopper(stop_event)
                finally:
                    broadcaster_task.cancel()
                    health_task.cancel()
                    log_task.cancel()
                    with contextlib.suppress(Exception):
                        await broadcaster_task
                    with contextlib.suppress(Exception):
                        await health_task
                    with contextlib.suppress(Exception):
                        await log_task
            break
        except OSError as exc:
            if _is_port_in_use_error(exc):
                print(
                    f"UI Lite порт зайнятий {config.ui_lite_host}:{config.ui_lite_port}, повтор через 2с.",
                    file=sys.stderr,
                    flush=True,
                )
                await asyncio.sleep(2.0)
                continue
            stop_event.set()
            raise RuntimeError(f"Не вдалося підняти UI Lite на {config.ui_lite_host}:{config.ui_lite_port}: {exc}")


async def _stopper(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        await asyncio.sleep(0.2)


def start_ui_lite(config: Config, redis_client: redis.Redis) -> UiLiteHandle:
    stop_event = threading.Event()

    def _runner() -> None:
        asyncio.run(_run_server(config, redis_client, stop_event))

    thread = threading.Thread(target=_runner, name="ui_lite", daemon=True)
    thread.start()
    return UiLiteHandle(thread=thread, stop_event=stop_event)


def main() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    load_env(root_dir)
    config = load_config()
    redis_client = redis.Redis.from_url(config.redis_dsn(), decode_responses=True)
    stop_event = threading.Event()
    try:
        print("UI Lite стартує…", file=sys.stderr, flush=True)
        asyncio.run(_run_server(config, redis_client, stop_event))
    except KeyboardInterrupt:
        stop_event.set()
    except Exception as exc:
        print(f"UI Lite запуск зірвався: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise
    finally:
        print("UI Lite зупинено примусово (Ctrl+C).", file=sys.stderr, flush=True)
        stop_event.set()


if __name__ == "__main__":
    main()
