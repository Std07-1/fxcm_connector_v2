from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from hashlib import sha256
from http import HTTPStatus
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Set, Tuple

import redis
from websockets.datastructures import Headers
from websockets.legacy.server import WebSocketServerProtocol, serve

from config.config import Config, load_config
from core.env_loader import load_env
from core.time.buckets import TF_TO_MS, get_bucket_open_ms
from core.time.calendar import Calendar
from core.time.sessions import _to_utc_iso
from core.validation.validator import ContractError, SchemaValidator
from runtime.command_auth import _canonical_payload, _resolve_secrets

log = logging.getLogger("ui_lite")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

_WS_LOGGERS = ("websockets", "websockets.server", "websockets.client")
for _name in _WS_LOGGERS:
    logging.getLogger(_name).setLevel(logging.WARNING)


@dataclass
class UiLiteHandle:
    thread: threading.Thread
    stop_event: threading.Event

    def stop(self) -> None:
        self.stop_event.set()
        try:
            self.thread.join(timeout=2.0)
        except KeyboardInterrupt:
            log.warning("Отримано KeyboardInterrupt. UI Lite завершено примусово")
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


def _grace_ms_for_tf(tf: str) -> int:
    if tf == "1m":
        return 5_000
    if tf == "15m":
        return 60_000
    return 0


def _compute_preview_stale_state(
    now_ms: int,
    last_open_by_tf: Dict[str, Any],
    calendar: Optional[Calendar],
    market_open: bool,
) -> Tuple[str, int, int, int]:
    if not market_open:
        return "", 0, 0, 0
    stale_tf = ""
    stale_delay_bars = 0
    expected_open_ms = 0
    last_open_ms = 0
    for tf_key, open_ms in last_open_by_tf.items():
        tf_str = str(tf_key)
        tf_ms = TF_TO_MS.get(tf_str)
        if tf_ms is None:
            continue
        try:
            open_ms_int = int(open_ms)
        except Exception:
            continue
        if calendar is None and tf_str == "1d":
            continue
        expected_ms = get_bucket_open_ms(tf_str, now_ms, calendar)
        grace_ms = _grace_ms_for_tf(tf_str)
        expected_for_delay = int(expected_ms)
        if grace_ms > 0 and now_ms - int(expected_ms) <= grace_ms:
            expected_for_delay = int(expected_ms) - int(tf_ms)
        delay_bars = max(0, int((expected_for_delay - open_ms_int) // tf_ms))
        if delay_bars >= stale_delay_bars:
            stale_delay_bars = delay_bars
            stale_tf = tf_str
            expected_open_ms = int(expected_ms)
            last_open_ms = int(open_ms_int)
    return stale_tf, stale_delay_bars, expected_open_ms, last_open_ms


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
    preview_publish_interval_ms: int = 0
    calendar: Optional[Calendar] = None
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
    last_payload_rx_ms: int = 0
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
    status_fresh_warn_ms: int = 5000
    status_publish_period_ms: int = 1000

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "subscribed_channel": self.subscribed_channel,
                "preview_publish_interval_ms": self.preview_publish_interval_ms,
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
                "last_payload_rx_ms": self.last_payload_rx_ms,
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
                "status_fresh_warn_ms": self.status_fresh_warn_ms,
                "status_publish_period_ms": self.status_publish_period_ms,
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
            log.debug("UI Lite HTTP %s -> %s", path, response[0])
            return response
        if path == "/app.js":
            file_path = static_dir / "app.js"
            response = _read_file(file_path, "application/javascript; charset=utf-8")
            log.debug("UI Lite HTTP %s -> %s", path, response[0])
            return response
        if path == "/chart_adapter.js":
            file_path = static_dir / "chart_adapter.js"
            response = _read_file(file_path, "application/javascript; charset=utf-8")
            log.debug("UI Lite HTTP %s -> %s", path, response[0])
            return response
        if path == "/styles.css":
            file_path = static_dir / "styles.css"
            response = _read_file(file_path, "text/css; charset=utf-8")
            log.debug("UI Lite HTTP %s -> %s", path, response[0])
            return response
        if path == "/vendor/lightweight-charts.standalone.production.js":
            file_path = static_dir / "vendor" / "lightweight-charts.standalone.production.js"
            response = _read_file(file_path, "application/javascript; charset=utf-8")
            log.debug("UI Lite HTTP %s -> %s", path, response[0])
            return response
        if path == "/favicon.ico":
            response = (
                HTTPStatus.NO_CONTENT,
                _make_headers("image/x-icon", 0),
                b"",
            )
            log.debug("UI Lite HTTP %s -> %s", path, response[0])
            return response
        body = b"not found"
        response = (
            HTTPStatus.NOT_FOUND,
            _make_headers("text/plain; charset=utf-8", len(body)),
            body,
        )
        log.debug("UI Lite HTTP %s -> %s", path, response[0])
        return response
    except Exception as exc:
        msg = f"process_request error: {exc}".encode("utf-8")
        headers = _make_headers("text/plain; charset=utf-8", len(msg))
        log.error("UI Lite HTTP %s -> 500", path)
        return HTTPStatus.INTERNAL_SERVER_ERROR, headers, msg


def _sign_command_payload(payload: Dict[str, Any], config: Config) -> Tuple[bool, str, Dict[str, Any]]:
    secrets, default_kid = _resolve_secrets(config)
    kid = str(payload.get("auth_kid", "")).strip() or str(default_kid or "").strip()
    if not kid:
        return False, "auth_secret_missing", {}
    secret = secrets.get(kid, "")
    if not secret:
        return False, "auth_secret_missing", {}
    nonce = str(payload.get("req_id", "")).strip() or f"ui-{int(time.time() * 1000)}"
    canonical = _canonical_payload(payload, kid=kid, nonce=nonce)
    sig = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), sha256).hexdigest()
    signed = dict(payload)
    signed["auth"] = {"kid": kid, "sig": sig, "nonce": nonce}
    return True, "ok", signed


def _publish_command(redis_client: redis.Redis, config: Config, payload: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return False, "command_encode_failed"
    try:
        redis_client.publish(config.ch_commands(), raw)
    except Exception:
        return False, "command_publish_failed"
    return True, "ok"


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
    config: Config,
    redis_client: redis.Redis,
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
            msg_type = payload.get("type")
            if msg_type == "subscribe":
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
                continue
            if msg_type == "command":
                cmd = str(payload.get("cmd", "")).strip()
                args = payload.get("args", {})
                if not cmd:
                    response = {"type": "command_ack", "ok": False, "error": "missing_cmd"}
                    await websocket.send(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
                    with _STATE.lock:
                        _STATE.ws_tx_total += 1
                    continue
                if not isinstance(args, dict):
                    response = {"type": "command_ack", "ok": False, "error": "invalid_args"}
                    await websocket.send(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
                    with _STATE.lock:
                        _STATE.ws_tx_total += 1
                    continue
                now_ms = int(time.time() * 1000)
                req_id = str(payload.get("req_id", "")).strip() or f"ui-{now_ms}"
                base_payload = {"cmd": cmd, "req_id": req_id, "ts": now_ms, "args": args}
                ok, reason, signed = _sign_command_payload(base_payload, config)
                if not ok:
                    response = {"type": "command_ack", "ok": False, "error": reason}
                    await websocket.send(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
                    with _STATE.lock:
                        _STATE.ws_tx_total += 1
                    continue
                ok, reason = _publish_command(redis_client, config, signed)
                response = {"type": "command_ack", "ok": ok, "error": None if ok else reason, "req_id": req_id}
                await websocket.send(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
                with _STATE.lock:
                    _STATE.ws_tx_total += 1
                continue
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
                _STATE.last_payload_rx_ms = int(time.time() * 1000)
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
        market = status_payload.get("market")
        market_open = bool(market.get("is_open", True)) if isinstance(market, dict) else True
        heartbeat_warn_ms = int(_STATE.status_fresh_warn_ms)
        heartbeat_hard_warn_ms = int(_STATE.status_publish_period_ms) * 10
        if market_open:
            status_stale = bool(status_age_ms is not None and status_age_ms > heartbeat_warn_ms)
        else:
            status_stale = bool(status_age_ms is not None and status_age_ms > heartbeat_hard_warn_ms)
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
    last_log_ms = 0
    last_rx_total = 0
    last_tx_total = 0
    last_json_err = 0
    last_contract_err = 0
    last_status_invalid = 0
    last_ohlcv_invalid = 0
    last_clients: Optional[int] = None
    last_status_ok: Optional[bool] = None
    last_rails: Tuple[int, int, int] = (0, 0, 0)
    last_summary_meta_ms = 0
    while not stop_event.is_set():
        await asyncio.sleep(5.0)
        now_ms = int(time.time() * 1000)
        snap = _STATE.snapshot()
        rx_total = int(snap.get("redis_rx_total", 0))
        tx_total = int(snap.get("ws_tx_total", 0))
        json_err = int(snap.get("redis_json_err_total", 0))
        contract_err = int(snap.get("redis_contract_err_total", 0))
        status_invalid = int(snap.get("status_invalid_total", 0))
        ohlcv_invalid = int(snap.get("ohlcv_inbound_invalid_total", 0))
        clients = int(snap.get("ws_clients", 0))
        status_ok = bool(snap.get("status_ok", False))
        publish_interval_ms = int(snap.get("preview_publish_interval_ms", 0))
        calendar = _STATE.calendar
        if publish_interval_ms <= 0:
            publish_interval_ms = 1000

        error_changed = (
            json_err > last_json_err
            or contract_err > last_contract_err
            or status_invalid > last_status_invalid
            or ohlcv_invalid > last_ohlcv_invalid
        )
        clients_changed = last_clients is not None and clients != last_clients
        status_changed = last_status_ok is not None and status_ok != last_status_ok
        time_due = now_ms - last_log_ms >= 60_000

        if not (time_due or error_changed or clients_changed or status_changed):
            continue

        rx_delta = rx_total - last_rx_total
        tx_delta = tx_total - last_tx_total
        payload_rx_ms = int(snap.get("last_payload_rx_ms", 0))
        payload_ts_ms = int(snap.get("last_payload_ts_ms", 0))
        payload_age_ms = (now_ms - payload_ts_ms) if payload_ts_ms > 0 else None
        if payload_rx_ms > 0:
            payload_age_ms = now_ms - payload_rx_ms
        status_ts_ms = int(snap.get("last_status_ts_ms", 0))
        status_age_ms = (now_ms - status_ts_ms) if status_ts_ms > 0 else None
        last_tf = str(snap.get("last_payload_tf", ""))
        payload_age_s = (payload_age_ms / 1000.0) if payload_age_ms is not None else None
        status_age_s = (status_age_ms / 1000.0) if status_age_ms is not None else None

        status_snapshot = snap.get("last_status_snapshot")
        status_payload: Dict[str, Any] = status_snapshot if isinstance(status_snapshot, dict) else {}
        price_raw = status_payload.get("price")
        fxcm_raw = status_payload.get("fxcm")
        preview_raw = status_payload.get("ohlcv_preview")
        market_raw = status_payload.get("market")
        price: Dict[str, Any] = price_raw if isinstance(price_raw, dict) else {}
        fxcm: Dict[str, Any] = fxcm_raw if isinstance(fxcm_raw, dict) else {}
        preview: Dict[str, Any] = preview_raw if isinstance(preview_raw, dict) else {}
        market: Dict[str, Any] = market_raw if isinstance(market_raw, dict) else {}
        last_publish_ts_ms = int(preview.get("last_publish_ts_ms", 0))
        ohlcv_age_s = (now_ms - last_publish_ts_ms) / 1000.0 if last_publish_ts_ms > 0 else None
        tick_lag_ms = int(price.get("tick_lag_ms", 0))
        tick_lag_s = tick_lag_ms / 1000.0 if tick_lag_ms > 0 else 0.0
        fxcm_state = str(fxcm.get("state", ""))
        market_open = bool(market.get("is_open", True))
        next_open_utc = str(market.get("next_open_utc", ""))
        late_drop = int(preview.get("late_ticks_dropped_total", 0))
        misalign = int(preview.get("misaligned_open_time_total", 0))
        past_mut = int(preview.get("past_mutations_total", 0))
        rails_changed = (late_drop, misalign, past_mut) != last_rails

        if fxcm_state in {"", "connecting"}:
            last_rx_total = rx_total
            last_tx_total = tx_total
            last_json_err = json_err
            last_contract_err = contract_err
            last_status_invalid = status_invalid
            last_ohlcv_invalid = ohlcv_invalid
            last_clients = clients
            last_status_ok = status_ok
            continue

        last_open_map = preview.get("last_bar_open_time_ms")
        last_open_by_tf = last_open_map if isinstance(last_open_map, dict) else {}
        freshest_tf = ""
        freshest_open_ms = 0
        for tf_key, open_ms in last_open_by_tf.items():
            try:
                open_ms_int = int(open_ms)
            except Exception:
                continue
            if open_ms_int > freshest_open_ms:
                freshest_open_ms = open_ms_int
                freshest_tf = str(tf_key)

        stale_tf = ""
        stale_delay_bars = 0
        expected_open_ms = 0
        last_open_ms = 0
        if market_open:
            stale_tf, stale_delay_bars, expected_open_ms, last_open_ms = _compute_preview_stale_state(
                now_ms=now_ms,
                last_open_by_tf=last_open_by_tf,
                calendar=calendar,
                market_open=market_open,
            )

        expected_open_utc = _to_utc_iso(expected_open_ms) if expected_open_ms > 0 else "-"
        last_open_utc = _to_utc_iso(last_open_ms) if last_open_ms > 0 else "-"

        transport = "OK"
        transport_reason = "ok"
        next_action = "-"
        if fxcm_state == "connecting":
            transport = "WARN"
            transport_reason = "fxcm_connecting"
            next_action = "очікується FXCM login"
        if not status_ok:
            transport = "WARN"
            transport_reason = "status_missing"
            next_action = "перевірити status snapshot"
        status_warn_s = _STATE.status_fresh_warn_ms / 1000.0
        status_hard_warn_s = (_STATE.status_publish_period_ms * 10) / 1000.0
        status_warn_allowed = market_open or (status_age_s is not None and status_age_s > status_hard_warn_s)
        if status_warn_allowed and status_age_s is not None and status_age_s > status_warn_s * 2:
            transport = "ERROR"
            transport_reason = "status_stale"
            next_action = "перевірити status publisher"
        elif status_warn_allowed and status_age_s is not None and status_age_s > status_warn_s:
            transport = "WARN"
            transport_reason = "status_lag"
            next_action = "перевірити status publisher"

        if market_open and ohlcv_age_s is not None:
            if ohlcv_age_s > 30.0:
                transport = "ERROR"
                transport_reason = "ohlcv_stale"
                next_action = "перевірити publish OHLCV preview"
            elif ohlcv_age_s > 15.0:
                transport = "WARN"
                transport_reason = "ohlcv_lag"
                next_action = "перевірити publish OHLCV preview"
            elif ohlcv_age_s > 2.0 and transport == "OK":
                transport = "WARN"
                transport_reason = "ohlcv_lag"

        if tick_lag_s > 5.0:
            transport = "ERROR"
            transport_reason = "tick_lag"
            next_action = "перевірити FXCM стрім/підключення"
        elif tick_lag_s > 1.0 and transport == "OK":
            transport = "WARN"
            transport_reason = "tick_lag"

        data_state = "OK"
        if market_open:
            if stale_delay_bars >= 3:
                data_state = "ERROR"
            elif stale_delay_bars >= 1:
                data_state = "WARN"

        health = transport
        if transport == "OK" and data_state != "OK":
            health = data_state
        if not market_open and transport == "OK" and data_state == "OK":
            transport_reason = "paused_market_closed"
            if next_open_utc:
                next_action = f"next_open={next_open_utc}"

        status_age_str = f"{status_age_s:.1f}s" if status_age_s is not None else "-"
        ohlcv_age_str = f"{ohlcv_age_s:.1f}s" if ohlcv_age_s is not None else "-"
        payload_age_str = f"{payload_age_s:.1f}s" if payload_age_s is not None else "-"
        tx_suffix = " (no_clients)" if clients == 0 else ""
        fresh_tf = freshest_tf or "-"
        last_tf_short = last_tf or "-"
        keys_line = f"keys: fresh={fresh_tf} last={last_tf_short}"
        data_tf = stale_tf or fresh_tf
        exp_time = expected_open_utc
        got_time = last_open_utc
        if exp_time != "-" and "T" in exp_time:
            exp_time = exp_time.split("T", 1)[1][:5] + "Z"
        if got_time != "-" and "T" in got_time:
            got_time = got_time.split("T", 1)[1][:5] + "Z"
        data_line = f"{data_tf} exp={exp_time} got={got_time} delay={stale_delay_bars}"

        log_level = log.info if health == "OK" else log.warning
        log_level(
            "UI_LITE: \n"
            "Health=%s transport=%s data=%s fxcm=%s \n"
            "IO clients=%s rx=+%s/5s tx=+%s/5s%s \n"
            "FRESH status=%s ohlcv=%s payload=%s tick=%.1fs \n%s | %s | %s \n"
            "Rails late=%s mis=%s past=%s%s \n",
            health,
            transport,
            data_state,
            fxcm_state,
            clients,
            rx_delta,
            tx_delta,
            tx_suffix,
            status_age_str,
            ohlcv_age_str,
            payload_age_str,
            tick_lag_s,
            keys_line,
            data_line,
            transport_reason if health != "OK" else "-",
            late_drop,
            misalign,
            past_mut,
            f" | next={next_action}" if health != "OK" else "",
        )

        if (
            stale_delay_bars > 0
            or transport != "OK"
            or data_state != "OK"
            or rails_changed
            or late_drop
            or misalign
            or past_mut
        ):
            summary_parts = []
            if stale_tf and stale_delay_bars > 0:
                delay_s = float(stale_delay_bars * (TF_TO_MS.get(stale_tf, 0) or 0)) / 1000.0
                if last_open_ms <= 0:
                    delay_str = "-"
                elif delay_s >= 3600.0:
                    delay_str = f"{delay_s / 3600.0:.1f}h"
                else:
                    delay_str = f"{delay_s / 60.0:.1f}m"
                expected_short = expected_open_utc
                last_short = last_open_utc
                if expected_short != "-" and "T" in expected_short:
                    expected_short = expected_short.split("T", 1)[1][:5] + "Z"
                if last_short != "-" and "T" in last_short:
                    last_short = last_short.split("T", 1)[1][:5] + "Z"
                summary_parts.append(
                    "stale_tf={tf} delay={delay} expected={expected} last={last}".format(
                        tf=stale_tf,
                        delay=delay_str,
                        expected=expected_short,
                        last=last_short,
                    )
                )
            if summary_parts:
                log.warning("ohlcv_preview %s", "; ".join(summary_parts))
            top_parts = []
            if market_open:
                for tf_key, open_ms in last_open_by_tf.items():
                    tf_str = str(tf_key)
                    tf_ms = TF_TO_MS.get(tf_str)
                    if tf_ms is None:
                        continue
                    try:
                        open_ms_int = int(open_ms)
                    except Exception:
                        continue
                    if calendar is None and tf_str == "1d":
                        continue
                    expected_ms = get_bucket_open_ms(tf_str, now_ms, calendar)
                    grace_ms = _grace_ms_for_tf(tf_str)
                    expected_for_delay = int(expected_ms)
                    if grace_ms > 0 and now_ms - int(expected_ms) <= grace_ms:
                        expected_for_delay = int(expected_ms) - int(tf_ms)
                    delay_bars = max(0, int((expected_for_delay - open_ms_int) // tf_ms))
                    if delay_bars > 0:
                        if open_ms_int <= 0:
                            continue
                        delay_s = float(delay_bars * tf_ms) / 1000.0
                        if delay_s >= 3600.0:
                            delay_str = f"{delay_s / 3600.0:.1f}h"
                        else:
                            delay_str = f"{delay_s / 60.0:.1f}m"
                        top_parts.append(f"{tf_key}:delay={delay_str}")
            if top_parts:
                log.warning("top_tf: %s", ", ".join(top_parts[:4]))

        if now_ms - last_summary_meta_ms >= 600_000:
            market_raw = status_payload.get("market")
            market = market_raw if isinstance(market_raw, dict) else {}
            calendar_tag = str(market.get("calendar_tag", ""))
            if calendar_tag:
                log.debug("calendar_tag=%s", calendar_tag)
            last_summary_meta_ms = now_ms

        last_log_ms = now_ms
        last_rx_total = rx_total
        last_tx_total = tx_total
        last_json_err = json_err
        last_contract_err = contract_err
        last_status_invalid = status_invalid
        last_ohlcv_invalid = ohlcv_invalid
        last_clients = clients
        last_status_ok = status_ok
        last_rails = (late_drop, misalign, past_mut)


async def _run_server(config: Config, redis_client: redis.Redis, stop_event: threading.Event) -> None:
    clients: Set[WebSocketServerProtocol] = set()
    queue: asyncio.Queue = asyncio.Queue()
    dedup = DedupIndex()
    subs: Dict[WebSocketServerProtocol, Dict[str, Any]] = {}
    loop = asyncio.get_running_loop()
    validator = SchemaValidator(root_dir=Path(__file__).resolve().parents[1])
    with _STATE.lock:
        _STATE.subscribed_channel = config.ch_ohlcv()
        _STATE.preview_publish_interval_ms = int(config.ohlcv_preview_publish_interval_ms)
        _STATE.status_fresh_warn_ms = int(config.status_fresh_warn_ms)
        _STATE.status_publish_period_ms = int(config.status_publish_period_ms)
        _STATE.calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
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
                lambda ws, _path: _ws_handler(ws, clients, subs, config, redis_client),
                host=config.ui_lite_host,
                port=config.ui_lite_port,
                process_request=_process_request,  # type: ignore[arg-type]
            ):
                log.info("UI Lite слухає http://%s:%s", config.ui_lite_host, config.ui_lite_port)
                broadcaster_task = asyncio.create_task(_broadcaster(queue, clients, dedup, subs))
                health_task = asyncio.create_task(_health_broadcaster(stop_event, clients))
                log_task = asyncio.create_task(_log_state(stop_event))

                def _on_broadcaster_done(task: asyncio.Task) -> None:
                    if task.cancelled():
                        return
                    exc = task.exception()
                    if exc is not None:
                        log.error("UI Lite broadcaster error: %s", exc)

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
                log.warning(
                    "UI Lite порт зайнятий %s:%s, повтор через 2с.",
                    config.ui_lite_host,
                    config.ui_lite_port,
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
        log.info("UI Lite стартує…")
        asyncio.run(_run_server(config, redis_client, stop_event))
    except KeyboardInterrupt:
        stop_event.set()
    except Exception as exc:
        log.error("UI Lite запуск зірвався: %s", exc)
        log.exception("UI Lite traceback")
        raise
    finally:
        log.info("UI Lite зупинено примусово (Ctrl+C).")
        stop_event.set()


if __name__ == "__main__":
    main()
