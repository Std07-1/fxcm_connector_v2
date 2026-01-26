from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core.time.buckets import TF_TO_MS
from store.derived_builder import build_htf_final
from store.sqlite_store import SQLiteStore


def _make_1m_bars(symbol: str, start_ms: int, count: int) -> List[Dict[str, Any]]:
    bars: List[Dict[str, Any]] = []
    t = start_ms
    for i in range(count):
        bar = {
            "symbol": symbol,
            "open_time_ms": t,
            "close_time_ms": t + 60_000 - 1,
            "open": 1.0 + i,
            "high": 1.1 + i,
            "low": 0.9 + i,
            "close": 1.05 + i,
            "volume": 1,
            "complete": 1,
            "synthetic": 0,
            "source": "history",
            "event_ts_ms": t + 60_000 - 1,
            "ingest_ts_ms": t + 1000,
        }
        bars.append(bar)
        t += 60_000
    return bars


def _validate_htf(rows: List[Dict[str, Any]], tf: str) -> Tuple[bool, str]:
    if not rows:
        return False, "HTF порожній"
    seen = set()
    last_open = None
    for row in rows:
        open_ms = int(row["open_time_ms"])
        close_ms = int(row["close_time_ms"])
        if last_open is not None and open_ms < last_open:
            return False, "bars не відсортовані"
        if open_ms in seen:
            return False, "bars містять дублі"
        if close_ms != open_ms + TF_TO_MS[tf] - 1:
            return False, "close_time має бути inclusive"
        if int(row.get("complete", 0)) != 1:
            return False, "complete має бути 1"
        if int(row.get("synthetic", 1)) != 0:
            return False, "synthetic має бути 0"
        if row.get("source") != "history_agg":
            return False, "source має бути history_agg"
        if int(row.get("event_ts_ms", 0)) != close_ms:
            return False, "event_ts має дорівнювати close_time"
        seen.add(open_ms)
        last_open = open_ms
    return True, "OK"


def run() -> Tuple[bool, str]:
    symbol = "XAUUSD"
    base = 1_700_000_000_000
    base -= base % TF_TO_MS["5m"]
    schema = Path(__file__).resolve().parents[3] / "store" / "schema.sql"
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "gate.sqlite"
        store = SQLiteStore(db_path=db_path)
        store.init_schema(schema)
        bars_1m = _make_1m_bars(symbol, base, 5)
        store.upsert_bars(bars_1m)
        htf_bars, _ = build_htf_final(symbol, "5m", bars_1m)
        for bar in htf_bars:
            bar["ingest_ts_ms"] = base + 1000
        store.upsert_htf_final(symbol, "5m", htf_bars)
        rows = store.query_htf_range(symbol, "5m", base, base + TF_TO_MS["5m"] - 1, 10)
    ok, msg = _validate_htf(rows, "5m")
    if not ok:
        return False, msg
    return True, "OK: final_wire_from_store"
