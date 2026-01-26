from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.publisher import RedisPublisher
from runtime.rebuild_derived import DerivedRebuildCoordinator
from runtime.status import StatusManager
from runtime.tail_guard import run_tail_guard
from store.sqlite_store import SQLiteStore
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


def test_tail_guard_deferred_when_market_open(tmp_path: Path, monkeypatch) -> None:
    freeze_time(monkeypatch)
    db = tmp_path / "test.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)

    config = Config(tail_guard_safe_repair_only_when_market_closed=True)
    calendar = Calendar([], config.calendar_tag)
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
    store.upsert_1m_final(
        "XAUUSD",
        [
            {
                "symbol": "XAUUSD",
                "open_time_ms": end_open_ms,
                "close_time_ms": end_open_ms + 60_000 - 1,
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1.0,
                "complete": 1,
                "synthetic": 0,
                "source": "history",
                "event_ts_ms": end_open_ms + 60_000 - 1,
                "ingest_ts_ms": now_ms,
            }
        ],
    )

    result = run_tail_guard(
        config=config,
        store=store,
        calendar=calendar,
        provider=None,
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

    state = result.tf_states["1m"]
    assert state.status == "deferred"
    assert "repair_deferred_market_open" in status.snapshot().get("degraded", [])
