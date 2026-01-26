from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Tuple

from config.config import load_config
from core.env_loader import load_env
from core.time.buckets import TF_TO_MS
from store.sqlite_store import SQLiteStore


def _validate_tail(store: SQLiteStore, symbol: str, tf: str, hours: int) -> Tuple[bool, str]:
    if tf not in {"15m", "1h", "4h", "1d"}:
        return False, "tf має бути 15m/1h/4h/1d"
    limit = max(1, int(hours * 60 * 60 * 1000 / TF_TO_MS[tf])) + 5
    rows = store.query_htf_tail(symbol, tf, limit)
    for row in rows:
        open_time = int(row["open_time_ms"])
        close_time = int(row["close_time_ms"])
        if open_time % TF_TO_MS[tf] != 0:
            return False, "open_time має бути вирівняний по bucket"
        if close_time != open_time + TF_TO_MS[tf] - 1:
            return False, "close_time має дорівнювати bucket_end_ms - 1"
        if int(row.get("complete", 1)) != 1:
            return False, "complete має бути 1"
        if int(row.get("synthetic", 0)) != 0:
            return False, "synthetic має бути 0"
        if row.get("source") != "history_agg":
            return False, "source має бути history_agg"
        if int(row.get("event_ts_ms", 0)) != close_time:
            return False, "event_ts має дорівнювати close_time"
    return True, "OK: final_wire"


def run() -> Tuple[bool, str]:
    return True, "SKIP: gate_final_wire запускається вручну через CLI"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--tf", required=True)
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parents[3]
    load_env(root_dir)
    config = load_config()
    store = SQLiteStore(db_path=Path(config.store_path))
    store.init_schema(Path(__file__).resolve().parents[3] / "store" / "schema.sql")

    ok, message = _validate_tail(store, args.symbol, args.tf, args.hours)
    if ok:
        print("OK: final_wire")
        return 0
    print(f"FAIL: {message}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
