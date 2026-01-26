from __future__ import annotations

import os
import time
from typing import Set, Tuple

import redis

from config.config import Config


def run() -> Tuple[bool, str]:
    ns = os.environ.get("FXCM_NS", "fxcm_local")
    redis_host = os.environ.get("FXCM_REDIS_HOST", "127.0.0.1")
    redis_port = int(os.environ.get("FXCM_REDIS_PORT", "6379"))
    timeout_s = int(os.environ.get("FXCM_MULTI_TF_TIMEOUT_S", "15"))
    required = os.environ.get("FXCM_MULTI_TF_LIST", "1m,5m,15m")

    required_tfs: Set[str] = {tf.strip() for tf in required.split(",") if tf.strip()}
    if not required_tfs:
        return False, "FAIL: required TF list порожній"

    cfg = Config(ns=ns, commands_enabled=False)
    channel = cfg.ch_ohlcv()

    client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(channel)

    seen: Set[str] = set()
    deadline = time.time() + max(1, timeout_s)
    while time.time() < deadline and seen != required_tfs:
        message = pubsub.get_message(timeout=1.0)
        if not message or message.get("type") != "message":
            continue
        payload = message.get("data")
        if not isinstance(payload, str):
            payload = str(payload)
        if '"tf"' not in payload:
            continue
        for tf in required_tfs:
            if f'"tf":"{tf}"' in payload or f'"tf": "{tf}"' in payload:
                seen.add(tf)

    pubsub.close()

    missing = required_tfs - seen
    if missing:
        return False, f"FAIL: не отримано TF: {', '.join(sorted(missing))}"
    return True, f"OK: отримано TF: {', '.join(sorted(seen))}"
