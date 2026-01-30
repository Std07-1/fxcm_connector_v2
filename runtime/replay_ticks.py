from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import redis

from config.config import Config
from core.market.preview_1m_builder import Preview1mBuilder
from core.market.replay_policy import TickReplayPolicy
from core.market.tick import tick_from_payload
from core.time.calendar import Calendar
from core.validation.validator import ContractError, SchemaValidator
from runtime.status import StatusManager


@dataclass
class ReplayTickHandle:
    thread: threading.Thread
    stop_event: threading.Event
    error: Optional[str] = None

    def stop(self) -> None:
        self.stop_event.set()
        try:
            self.thread.join(timeout=2.0)
        except KeyboardInterrupt:
            return


@dataclass
class ReplayTickStream:
    config: Config
    validator: SchemaValidator
    calendar: Calendar
    status: StatusManager
    on_tick: Callable[[str, float, float, float, int, int], None]
    _policy: TickReplayPolicy = field(init=False)

    def __post_init__(self) -> None:
        self._policy = TickReplayPolicy(calendar=self.calendar, validator=self.validator)

    def start(self) -> ReplayTickHandle:
        stop_event = threading.Event()
        handle = ReplayTickHandle(thread=threading.Thread(), stop_event=stop_event)
        thread = threading.Thread(target=self._run, args=(handle, stop_event), name="tick_replay")
        thread.daemon = True
        handle.thread = thread
        thread.start()
        return handle

    def _run(self, handle: Optional[ReplayTickHandle], stop_event: threading.Event) -> None:
        path = Path(self.config.replay_ticks_path)
        try:
            if not path.exists():
                raise ContractError(f"replay файл не знайдено: {path}")
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if not lines:
                raise ContractError("replay файл порожній")
            for line in lines:
                if stop_event.is_set():
                    return
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ContractError(f"replay JSONL невалідний: {exc}") from exc
                if not isinstance(payload, dict):
                    raise ContractError("replay рядок має бути JSON-об'єктом")
                self._policy.validate_payload(payload)
                symbol = payload.get("symbol")
                bid = payload.get("bid")
                ask = payload.get("ask")
                mid = payload.get("mid")
                tick_ts = payload.get("tick_ts")
                snap_ts = payload.get("snap_ts")
                if not isinstance(symbol, str) or not symbol:
                    raise ContractError("symbol має бути непорожнім рядком")
                if not isinstance(bid, (int, float)):
                    raise ContractError("bid має бути числом")
                if not isinstance(ask, (int, float)):
                    raise ContractError("ask має бути числом")
                if not isinstance(mid, (int, float)):
                    raise ContractError("mid має бути числом")
                if not isinstance(tick_ts, int) or isinstance(tick_ts, bool):
                    raise ContractError("tick_ts має бути int ms")
                if not isinstance(snap_ts, int) or isinstance(snap_ts, bool):
                    raise ContractError("snap_ts має бути int ms")
                self.on_tick(
                    symbol,
                    float(bid),
                    float(ask),
                    float(mid),
                    int(tick_ts),
                    int(snap_ts),
                )
        except ContractError as exc:
            self.status.append_error(
                code="tick_replay_error",
                severity="error",
                message=str(exc),
            )
            self.status.set_last_command_error("tick_replay", "replay", 0)
            self.status.publish_snapshot()
            if handle is not None:
                handle.error = str(exc)
            raise


def _parse_line(line: str) -> dict:
    payload = json.loads(line)
    if not isinstance(payload, dict):
        raise ContractError("рядок має бути JSON-об'єктом")
    return payload


def _sleep_ms(ms: int, speed: float) -> None:
    if ms <= 0 or speed <= 0:
        return
    time.sleep((ms / 1000.0) / speed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ns", default="fxcm_local")
    parser.add_argument("--redis-host", default="127.0.0.1")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--in", dest="in_path", required=True)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--publish_price_tik", action="store_true")
    parser.add_argument("--publish_ohlcv", action="store_true")
    args = parser.parse_args()

    in_path = Path(args.in_path)
    if not in_path.exists():
        raise SystemExit(f"Файл не знайдено: {in_path}")

    cfg = Config(ns=args.ns, commands_enabled=False)
    channel_price = cfg.ch_price_tik()
    channel_ohlcv = cfg.ch_ohlcv()
    validator = SchemaValidator(root_dir=Path(__file__).resolve().parents[1])
    calendar = Calendar(calendar_tag=cfg.calendar_tag, overrides_path=cfg.calendar_path)
    policy = TickReplayPolicy(calendar=calendar, validator=validator)

    client = redis.Redis(host=args.redis_host, port=args.redis_port, decode_responses=True)

    lines = [line for line in in_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise SystemExit("Вхідний файл порожній")

    prev_ts: Optional[int] = None
    count = 0
    builder = Preview1mBuilder()
    for line in lines:
        payload = _parse_line(line)
        policy.validate_payload(payload)
        tick = tick_from_payload(payload)
        tick_ts = tick.tick_ts_ms
        if prev_ts is not None:
            delta = max(0, tick_ts - prev_ts)
            _sleep_ms(delta, args.speed)
        prev_ts = tick_ts

        if args.publish_price_tik:
            client.publish(channel_price, json.dumps(payload, ensure_ascii=False))

        if args.publish_ohlcv:
            state = builder.on_tick(tick)
            ohlcv_payload = {
                "symbol": tick.symbol,
                "tf": "1m",
                "source": "stream",
                "bars": [state.to_dict()],
            }
            client.publish(channel_ohlcv, json.dumps(ohlcv_payload, ensure_ascii=False))

        count += 1

    channels = []
    if args.publish_price_tik:
        channels.append(channel_price)
    if args.publish_ohlcv:
        channels.append(channel_ohlcv)
    if not channels:
        channels.append("(no publish)")

    print(f"OK: replayed {count} ticks -> {', '.join(channels)}")


if __name__ == "__main__":
    main()
