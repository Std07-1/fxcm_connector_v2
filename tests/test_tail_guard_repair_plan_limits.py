from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import pytest

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.publisher import RedisPublisher
from runtime.rebuild_derived import DerivedRebuildCoordinator
from runtime.status import StatusManager
from runtime.tail_guard import run_tail_guard
from store.sqlite_store import SQLiteStore
from tests.fixtures.sim.history_sim_provider import HistorySimProvider
from tests.time_helpers import TEST_NOW_MS, freeze_time


class DummyRedis:
    def __init__(self) -> None:
        self._store: Dict[str, str] = {}

    def set(self, key: str, value: str) -> None:
        return None

    def publish(self, channel: str, value: str) -> None:
        return None

    def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    def setex(self, key: str, ttl_s: int, value: str) -> None:
        _ = ttl_s
        self._store[key] = value


def test_tail_guard_repair_plan_limits(tmp_path: Path, monkeypatch) -> None:
    freeze_time(monkeypatch)
    db = tmp_path / "test.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)

    config = Config(
        tail_guard_checked_ttl_s=0,
        tail_guard_safe_repair_only_when_market_closed=False,
        tail_guard_repair_max_missing_bars=1,
        tail_guard_repair_max_window_ms=60_000,
        tail_guard_repair_max_history_chunks=1,
    )
    calendar = Calendar([], config.calendar_tag)
    provider = HistorySimProvider(calendar=calendar)
    validator = SchemaValidator(root_dir=Path(__file__).resolve().parents[1])
    redis = DummyRedis()
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=RedisPublisher(redis, config),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()
    derived_rebuilder = DerivedRebuildCoordinator()

    now_ms = TEST_NOW_MS
    end_open_ms = now_ms - (now_ms % 60_000) - 60_000
    start_ms = end_open_ms - 60 * 60_000
    bars = provider.fetch_1m_final("XAUUSD", start_ms, end_open_ms, limit=2000)
    for bar in bars:
        bar["ingest_ts_ms"] = now_ms
    store.upsert_1m_final("XAUUSD", bars)

    missing_opens = [start_ms + 5 * 60_000, start_ms + 6 * 60_000, start_ms + 7 * 60_000]
    conn = store.connect()
    try:
        for open_ms in missing_opens:
            conn.execute(
                "DELETE FROM bars_1m_final WHERE symbol = ? AND open_time_ms = ?",
                ("XAUUSD", open_ms),
            )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError):
        run_tail_guard(
            config=config,
            store=store,
            calendar=calendar,
            provider=provider,
            redis_client=redis,
            derived_rebuilder=derived_rebuilder,
            publisher=RedisPublisher(redis, config),
            validator=validator,
            status=status,
            metrics=None,
            symbol="XAUUSD",
            window_hours=1,
            repair=True,
            republish_after_repair=False,
            republish_force=False,
            tfs=["1m"],
        )

    errors = status.snapshot().get("errors", [])
    assert any(err.get("code") == "repair_budget_exceeded" for err in errors)
