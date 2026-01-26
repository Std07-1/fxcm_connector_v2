from __future__ import annotations

from pathlib import Path

from store.sqlite_store import SQLiteStore


def test_store_coverage_empty(tmp_path: Path) -> None:
    db = tmp_path / "test.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)

    coverage = store.get_1m_coverage("XAUUSD")
    assert coverage["first_open_ms"] is None
    assert coverage["last_close_ms"] is None
    assert coverage["bars"] == 0
    assert coverage["coverage_days"] == 0


def test_store_coverage_non_empty(tmp_path: Path) -> None:
    db = tmp_path / "test.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)

    base = 1_736_980_000_000
    bars = []
    for i in range(3):
        open_ms = base + i * 60_000
        bars.append(
            {
                "symbol": "XAUUSD",
                "open_time_ms": open_ms,
                "close_time_ms": open_ms + 60_000 - 1,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "volume": 1.0,
                "complete": 1,
                "synthetic": 0,
                "source": "history",
                "event_ts_ms": open_ms + 60_000 - 1,
                "ingest_ts_ms": base + 5_000,
            }
        )
    store.upsert_bars(bars)

    coverage = store.get_1m_coverage("XAUUSD")
    assert coverage["first_open_ms"] == bars[0]["open_time_ms"]
    assert coverage["last_close_ms"] == bars[-1]["close_time_ms"]
    assert coverage["bars"] == 3
    assert coverage["coverage_days"] >= 0
