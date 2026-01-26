from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

import redis

from config.config import Config, load_config
from core.env_loader import load_env
from core.market.tick import tick_from_payload
from runtime.fxcm_forexconnect import check_fxcm_environment


def _default_out_dir(root_dir: Path) -> Path:
    return root_dir / "recordings" / "ticks"


def _parse_json(raw: Any) -> Dict[str, Any]:
    if raw is None:
        raise RuntimeError("порожній payload")
    if isinstance(raw, str):
        text = raw
    else:
        text = str(raw)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise RuntimeError("payload має бути об'єктом")
    return payload


def _require_int_ms(value: Any, field: str) -> int:
    if not isinstance(value, int):
        raise RuntimeError(f"{field} має бути int")
    if value < 1_000_000_000_000:
        raise RuntimeError(f"{field} має бути epoch ms (>=1e12)")
    return value


def _parse_symbols(value: str) -> Set[str]:
    if not value:
        return set()
    return {item.strip().upper().replace("/", "") for item in value.split(",") if item.strip()}


def _open_output_files(out: Path, symbols: Iterable[str]) -> Dict[str, Path]:
    out_paths: Dict[str, Path] = {}
    ts = int(time.time())
    for symbol in symbols:
        out_paths[symbol] = out / f"{symbol}_{ts}.jsonl"
    return out_paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ns", default="fxcm_local")
    parser.add_argument("--redis-host", default="127.0.0.1")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--symbols", default="XAUUSD")
    parser.add_argument("--duration_s", type=int, default=30)
    parser.add_argument("--out", default="")
    parser.add_argument("--mode", default="online")
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parents[1]
    load_env(root_dir)
    config = load_config()
    if args.mode == "online":
        ok, reason = check_fxcm_environment(config)
        if not ok:
            raise RuntimeError(f"FXCM not ready: {reason}")
        if config.fxcm_backend != "forexconnect":
            raise RuntimeError("fxcm_backend має бути forexconnect для online")

    cfg = Config(ns=args.ns, commands_enabled=False)
    channel = cfg.ch_price_tik()

    symbols = _parse_symbols(args.symbols)
    if not symbols:
        raise RuntimeError("symbols має бути непорожнім списком")

    out_path = Path(args.out) if args.out else _default_out_dir(root_dir)
    if out_path.suffix == ".jsonl" and len(symbols) != 1:
        raise RuntimeError("--out файл дозволено лише для одного символа")
    if out_path.suffix == ".jsonl":
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_paths = {next(iter(symbols)): out_path}
    else:
        out_path.mkdir(parents=True, exist_ok=True)
        out_paths = _open_output_files(out_path, symbols)

    client = redis.Redis(host=args.redis_host, port=args.redis_port, decode_responses=True)
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(channel)

    count = 0
    deadline = time.time() + max(1, args.duration_s)

    handles: Dict[str, Any] = {}
    for symbol, path in out_paths.items():
        handles[symbol] = path.open("w", encoding="utf-8")

    try:
        while time.time() < deadline:
            message = pubsub.get_message(timeout=1.0)
            if not message or message.get("type") != "message":
                continue
            payload = _parse_json(message.get("data"))
            _require_int_ms(payload.get("tick_ts_ms"), "tick_ts_ms")
            _require_int_ms(payload.get("snap_ts_ms"), "snap_ts_ms")
            tick = tick_from_payload(payload)
            if tick.symbol not in symbols:
                continue
            line = {
                **tick.to_dict(),
                "record_ts_ms": int(time.time() * 1000),
            }
            handles[tick.symbol].write(json.dumps(line, ensure_ascii=False) + "\n")
            count += 1
    finally:
        for handle in handles.values():
            handle.close()

    pubsub.close()

    if count == 0:
        raise RuntimeError("Не отримано жодного tick повідомлення")

    outputs: List[str] = [str(path.resolve()) for path in out_paths.values()]
    print(f"OK: captured {count} ticks -> {', '.join(outputs)}")


if __name__ == "__main__":
    main()
