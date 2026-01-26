from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Tuple

import redis

from config.config import load_config
from core.env_loader import load_env


def run() -> Tuple[bool, str]:
    return True, "SKIP: gate_republish_watermark запускається вручну через CLI"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--tfs", required=True)
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parents[3]
    load_env(root_dir)
    config = load_config()
    tfs = [tf.strip() for tf in args.tfs.split(",") if tf.strip()]
    if not tfs:
        print("FAIL: tfs порожній")
        return 2
    client = redis.Redis(
        host=config.redis_host,
        port=config.redis_port,
        decode_responses=True,
    )
    raw = client.get(config.key_status_snapshot())
    if not raw:
        print("FAIL: status:snapshot відсутній")
        return 2
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError:
        print("FAIL: status:snapshot невалідний JSON")
        return 2

    republish = snapshot.get("republish", {})
    if not isinstance(republish, dict):
        print("FAIL: republish секція відсутня")
        return 2
    if not republish.get("skipped_by_watermark", False):
        print("FAIL: skipped_by_watermark=false")
        return 2
    if int(republish.get("last_run_ts_ms", 0)) <= 0:
        print("FAIL: last_run_ts_ms=0")
        return 2

    print("OK: republish_watermark")
    return 0


if __name__ == "__main__":
    sys.exit(main())
