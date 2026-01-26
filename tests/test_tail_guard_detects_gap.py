from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from observability.metrics import create_metrics
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


def test_tail_guard_detects_gap(tmp_path: Path, monkeypatch) -> None:
    freeze_time(monkeypatch)
    db = tmp_path / "test.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)

    config = Config(tail_guard_checked_ttl_s=300)
    calendar = Calendar([], config.calendar_tag)
    metrics = create_metrics()
    validator = SchemaValidator(root_dir=Path(__file__).resolve().parents[1])
    redis = DummyRedis()
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=RedisPublisher(redis, config),
        calendar=calendar,
        metrics=metrics,
    )
    status.build_initial_snapshot()
    derived_rebuilder = DerivedRebuildCoordinator()

    now_ms = TEST_NOW_MS
    end_open_ms = now_ms - (now_ms % 60_000) - 60_000
    start_ms = end_open_ms - 59 * 60_000
    bars = []
    t = start_ms
    while t <= end_open_ms:
        bars.append(
            {
                "symbol": "XAUUSD",
                "open_time_ms": t,
                "close_time_ms": t + 60_000 - 1,
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1.0,
                "complete": 1,
                "synthetic": 0,
                "source": "history",
                "event_ts_ms": t + 60_000 - 1,
                "ingest_ts_ms": now_ms,
            }
        )
        t += 60_000
    store.upsert_1m_final("XAUUSD", bars)

    gap_open_ms = start_ms + 10 * 60_000
    conn = store.connect()
    try:
        conn.execute(
            "DELETE FROM bars_1m_final WHERE symbol = ? AND open_time_ms = ?",
            ("XAUUSD", gap_open_ms),
        )
        conn.commit()
    finally:
        conn.close()

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
        metrics=metrics,
        symbol="XAUUSD",
        window_hours=1,
        repair=False,
        republish_after_repair=False,
        republish_force=False,
        tfs=["1m"],
    )

    state = result.tf_states["1m"]
    assert state.status == "missing"
    assert state.missing_bars == 1
    assert state.missing_ranges
