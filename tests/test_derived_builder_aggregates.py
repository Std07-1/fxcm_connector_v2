from __future__ import annotations

import tempfile
from pathlib import Path

from store.bars_store import BarsStoreSQLite
from store.derived_builder import DerivedBuilder
from store.sqlite_store import SQLiteStore


def test_derived_builder_aggregates_15m() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "bars.sqlite"
        store = SQLiteStore(db_path=db_path)
        store.init_schema(root_dir / "store" / "schema.sql")

        base = 1_736_980_000_000
        open_start = base - (base % 900_000)
        bars = []
        for i in range(15):
            open_time = open_start + i * 60_000
            close_time = open_time + 60_000 - 1
            bars.append(
                {
                    "symbol": "XAUUSD",
                    "open_time_ms": open_time,
                    "close_time_ms": close_time,
                    "open": 100.0 + i,
                    "high": 101.0 + i,
                    "low": 99.0 + i,
                    "close": 100.5 + i,
                    "volume": 1.0,
                    "complete": 1,
                    "synthetic": 0,
                    "source": "history",
                    "event_ts_ms": close_time,
                    "ingest_ts_ms": close_time,
                }
            )
        store.upsert_1m_final("XAUUSD", bars)

        bars_store = BarsStoreSQLite(db_path=db_path, schema_path=root_dir / "store" / "schema.sql")
        builder = DerivedBuilder(bars_store=bars_store, trading_day_boundary_utc="22:00")
        end_ms = open_start + 900_000 - 1
        result = builder.build_range(
            symbol="XAUUSD",
            tf="15m",
            start_ms=open_start,
            end_ms=end_ms,
        )

    assert len(result) == 1
    bar = result[0]
    assert bar["open"] == 100.0
    assert bar["close"] == 114.5
    assert bar["high"] == 115.0
    assert bar["low"] == 99.0
    assert bar["volume"] == 15.0
    assert bar["event_ts"] == bar["close_time"]
