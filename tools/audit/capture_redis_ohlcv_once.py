from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

import redis

from config.config import Config, load_config
from core.env_loader import load_env
from runtime.fxcm_forexconnect import check_fxcm_environment


def _validate_bar(bar: Dict[str, Any]) -> None:
    open_time = bar.get("open_time", bar.get("open_time_ms"))
    close_time = bar.get("close_time", bar.get("close_time_ms"))
    if not isinstance(open_time, int) or open_time <= 0:
        raise RuntimeError("bar.open_time має бути > 0")
    if not isinstance(close_time, int) or close_time <= open_time:
        raise RuntimeError("bar.close_time має бути > open_time")
    if int(open_time / 1000) <= 0:
        raise RuntimeError("time_s має бути > 0")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ns", default="fxcm_local")
    parser.add_argument("--redis-host", default="127.0.0.1")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--out-path", required=True)
    parser.add_argument("--timeout-s", type=int, default=10)
    parser.add_argument("--mode", default="online")
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parents[2]
    load_env(root_dir)
    config = load_config()
    if args.mode == "online":
        ok, reason = check_fxcm_environment(config)
        if not ok:
            raise RuntimeError(f"FXCM not ready: {reason}")
        if config.fxcm_backend != "forexconnect":
            raise RuntimeError("fxcm_backend має бути forexconnect для online")

    cfg = Config(ns=args.ns, commands_enabled=False)
    channel = cfg.ch_ohlcv()

    client = redis.Redis(host=args.redis_host, port=args.redis_port, decode_responses=True)
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(channel)

    deadline = time.time() + max(1, args.timeout_s)
    payload = None
    while time.time() < deadline:
        message = pubsub.get_message(timeout=1.0)
        if not message:
            continue
        if message.get("type") != "message":
            continue
        raw = message.get("data")
        if raw is None:
            continue
        if isinstance(raw, str):
            text = raw
        else:
            text = str(raw)
        payload = json.loads(text)
        break

    pubsub.close()

    if payload is None:
        raise RuntimeError("Не отримано ohlcv повідомлення")
    bars = payload.get("bars", [])
    if not isinstance(bars, list) or not bars:
        raise RuntimeError("bars має бути непорожнім списком")
    _validate_bar(bars[0])

    out_path = Path(args.out_path)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: captured {channel} -> {out_path.resolve()}")


if __name__ == "__main__":
    main()
