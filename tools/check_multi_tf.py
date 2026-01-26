from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict, Set

import redis

from config.config import Config


def _parse_message(raw: Any) -> Dict[str, Any]:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ns", default="fxcm_local")
    parser.add_argument("--redis-host", default="127.0.0.1")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--timeout_s", type=int, default=15)
    parser.add_argument("--tfs", default="1m,5m,15m")
    args = parser.parse_args()

    cfg = Config(ns=args.ns, commands_enabled=False)
    channel = cfg.ch_ohlcv()
    required_tfs: Set[str] = {tf.strip() for tf in args.tfs.split(",") if tf.strip()}
    if not required_tfs:
        raise RuntimeError("tfs має бути непорожнім")

    client = redis.Redis(host=args.redis_host, port=args.redis_port, decode_responses=True)
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(channel)

    seen: Set[str] = set()
    deadline = time.time() + max(1, args.timeout_s)
    while time.time() < deadline and seen != required_tfs:
        message = pubsub.get_message(timeout=1.0)
        if not message or message.get("type") != "message":
            continue
        payload = _parse_message(message.get("data"))
        tf = payload.get("tf")
        if isinstance(tf, str) and tf in required_tfs:
            seen.add(tf)

    pubsub.close()

    missing = required_tfs - seen
    if missing:
        raise RuntimeError(f"Не отримано TF: {', '.join(sorted(missing))}")

    print(f"OK: отримано TF: {', '.join(sorted(seen))} у {channel}")


if __name__ == "__main__":
    main()
