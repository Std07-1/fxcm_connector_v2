from __future__ import annotations

from pathlib import Path

from store.sqlite_store import SQLiteStore


def test_store_upsert_and_query(tmp_path: Path) -> None:
    db = tmp_path / "test.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)

    bar = {
        "symbol": "XAUUSD",
        "open_time_ms": 1_736_980_000_000,
        "close_time_ms": 1_736_980_000_000 + 60_000 - 1,
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": 1.05,
        "volume": 1.0,
        "complete": 1,
        "synthetic": 0,
        "source": "history",
        "event_ts_ms": 1_736_980_000_000 + 60_000 - 1,
        "ingest_ts_ms": 1_736_980_100_000,
    }
    store.upsert_bars([bar])
    store.upsert_bars([bar])

    rows = store.query_tail("XAUUSD", 10)
    assert len(rows) == 1
    assert rows[0]["open_time_ms"] == bar["open_time_ms"]
