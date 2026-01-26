from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Tuple

from config.config import load_config
from core.env_loader import load_env
from core.time.buckets import TF_TO_MS
from core.time.calendar import Calendar
from store.sqlite_store import SQLiteStore


def check_calendar_gaps(
    store: SQLiteStore,
    calendar: Calendar,
    symbol: str,
    hours: int,
    tf: str,
) -> Tuple[int, bool]:
    real_now_ms = int(time.time() * 1000)
    if tf not in TF_TO_MS:
        raise ValueError("невідомий tf")
    size = TF_TO_MS[tf]

    if tf == "1m":
        tail = store.query_1m_tail(symbol, limit=1)
        if tail:
            end_open_ms = int(tail[-1]["open_time_ms"])
        else:
            end_open_ms = real_now_ms - (real_now_ms % 60_000) - 60_000
    else:
        tail = store.query_htf_tail(symbol, tf, limit=1)
        if tail:
            end_open_ms = int(tail[-1]["open_time_ms"])
        else:
            end_open_ms = real_now_ms - (real_now_ms % size)
    end_ms = end_open_ms + size - 1
    if end_ms % 60_000 != 59_999:
        raise ValueError("last_close_time не відповідає ...9999")
    if not calendar.is_open(end_ms, symbol=symbol):
        return 0, True

    if tf == "1m":
        start_open_ms = end_open_ms - (hours * 60 - 1) * 60_000
        start_ms = start_open_ms
        bars = store.query_range(symbol, start_ms, end_ms, limit=hours * 60 + 10)
        have = {int(b["open_time_ms"]) for b in bars}
    else:
        start_open_ms = end_open_ms - (hours * 60 * 60 * 1000) + size
        start_ms = start_open_ms
        bars = store.query_htf_range(
            symbol,
            tf,
            start_ms,
            end_ms,
            limit=int(hours * 60 * 60 * 1000 / size) + 10,
        )
        have = {int(b["open_time_ms"]) for b in bars}

    missing = 0
    t = start_open_ms
    while t <= end_open_ms:
        if calendar.is_open(t, symbol=symbol) and t not in have:
            missing += 1
        t += size

    return missing, False


def run() -> Tuple[bool, str]:
    return True, "SKIP: gate_calendar_gaps запускається вручну через CLI"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--tf", default="1m")
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parents[3]
    load_env(root_dir)
    config = load_config()
    store = SQLiteStore(db_path=Path(config.store_path))
    store.init_schema(Path(__file__).resolve().parents[3] / "store" / "schema.sql")

    calendar = Calendar(config.closed_intervals_utc, config.calendar_tag)
    tf = str(args.tf)
    try:
        missing, skipped = check_calendar_gaps(
            store=store,
            calendar=calendar,
            symbol=args.symbol,
            hours=args.hours,
            tf=tf,
        )
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 2

    if skipped:
        print("OK: trading time closed, gate skipped")
        return 0

    if missing == 0:
        print("OK: unexpected_missing_bars=0")
        return 0

    print(f"FAIL: unexpected_missing_bars={missing}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
