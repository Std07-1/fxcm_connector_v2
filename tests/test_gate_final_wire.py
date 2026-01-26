from __future__ import annotations

from pathlib import Path

from store.sqlite_store import SQLiteStore
from tools.exit_gates.gates.gate_final_wire import _validate_tail


def test_gate_final_wire_ok(tmp_path: Path) -> None:
    db = tmp_path / "test.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)

    base = 1_736_980_000_000
    open_time = base - (base % 900_000)
    close_time = open_time + 900_000 - 1
    store.upsert_htf_final(
        "XAUUSD",
        "15m",
        [
            {
                "symbol": "XAUUSD",
                "open_time_ms": open_time,
                "close_time_ms": close_time,
                "open": 1.0,
                "high": 1.2,
                "low": 0.9,
                "close": 1.1,
                "volume": 15.0,
                "complete": 1,
                "synthetic": 0,
                "source": "history_agg",
                "event_ts_ms": close_time,
                "ingest_ts_ms": 1_736_980_100_000,
            }
        ],
    )

    ok, _ = _validate_tail(store, "XAUUSD", "15m", hours=1)
    assert ok is True
