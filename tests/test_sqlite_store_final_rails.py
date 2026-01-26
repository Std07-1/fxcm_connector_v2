from __future__ import annotations

from pathlib import Path

import pytest

from core.validation.validator import ContractError
from store.sqlite_store import SQLiteStore


def _valid_bar() -> dict:
    base = 1_736_980_000_000
    return {
        "symbol": "XAUUSD",
        "open_time_ms": base,
        "close_time_ms": base + 60_000 - 1,
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": 1.05,
        "volume": 1.0,
        "complete": 1,
        "synthetic": 0,
        "source": "history",
        "event_ts_ms": base + 60_000 - 1,
        "ingest_ts_ms": base + 1000,
    }


def _store(tmp_path: Path) -> SQLiteStore:
    db = tmp_path / "test.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)
    return store


def test_final_1m_valid_passes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_bars([_valid_bar()])


def test_final_1m_source_invalid(tmp_path: Path) -> None:
    store = _store(tmp_path)
    bar = _valid_bar()
    bar["source"] = "stream"
    with pytest.raises(ContractError):
        store.upsert_bars([bar])


def test_final_1m_complete_invalid(tmp_path: Path) -> None:
    store = _store(tmp_path)
    bar = _valid_bar()
    bar["complete"] = 0
    with pytest.raises(ContractError):
        store.upsert_bars([bar])


def test_final_1m_synthetic_invalid(tmp_path: Path) -> None:
    store = _store(tmp_path)
    bar = _valid_bar()
    bar["synthetic"] = 1
    with pytest.raises(ContractError):
        store.upsert_bars([bar])


def test_final_1m_event_ts_invalid(tmp_path: Path) -> None:
    store = _store(tmp_path)
    bar = _valid_bar()
    bar["event_ts_ms"] = bar["close_time_ms"] - 1
    with pytest.raises(ContractError):
        store.upsert_bars([bar])


def test_final_1m_no_mix_conflict(tmp_path: Path) -> None:
    store = _store(tmp_path)
    bar = _valid_bar()
    conn = store.connect()
    try:
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute(
            """
            INSERT OR REPLACE INTO bars_1m_final (
              symbol, open_time_ms, close_time_ms, open, high, low, close, volume,
              complete, synthetic, source, event_ts_ms, ingest_ts_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bar["symbol"],
                bar["open_time_ms"],
                bar["close_time_ms"],
                bar["open"],
                bar["high"],
                bar["low"],
                bar["close"],
                bar["volume"],
                1,
                0,
                "stream",
                bar["event_ts_ms"],
                bar["ingest_ts_ms"],
            ),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(ContractError):
        store.upsert_bars([bar])
