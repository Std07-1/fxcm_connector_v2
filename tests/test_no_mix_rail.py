from __future__ import annotations

from pathlib import Path

import pytest

from core.validation.validator import ContractError
from store.sqlite_store import SQLiteStore


def test_no_mix_rejects_non_history_agg(tmp_path: Path) -> None:
    db = tmp_path / "test.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)

    bad_bar = {
        "symbol": "XAUUSD",
        "open_time_ms": 1_736_980_000_000,
        "close_time_ms": 1_736_980_000_000 + 900_000 - 1,
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": 1.05,
        "volume": 1.0,
        "complete": 1,
        "synthetic": 0,
        "source": "history",
        "event_ts_ms": 1_736_980_000_000 + 900_000 - 1,
        "ingest_ts_ms": 1_736_980_100_000,
    }

    with pytest.raises(ContractError):
        store.upsert_htf_final("XAUUSD", "15m", [bad_bar])
