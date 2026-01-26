from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.fxcm.history_budget import HistoryBudget
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


class DummyBudget(HistoryBudget):
    def __init__(self) -> None:
        super().__init__(capacity=1, refill_per_sec=1.0, tokens=1.0)
        self.acquired = 0
        self.released = 0

    def acquire(self, symbol: str) -> bool:
        _ = symbol
        self.acquired += 1
        return False

    def release(self, symbol: str) -> None:
        _ = symbol
        self.released += 1


class BudgetProbeProvider:
    def __init__(self, calendar: Calendar) -> None:
        self.calendar = calendar
        self.calls = 0
        self.ready = True
        self.retry_after_ms = 0

    def fetch_1m_final(self, symbol: str, start_ms: int, end_ms: int, limit: int):
        self.calls += 1
        bars: List[Dict[str, Any]] = []
        t = start_ms - (start_ms % 60_000)
        while t <= end_ms and len(bars) < limit:
            if not self.calendar.is_open(t, symbol=symbol):
                t += 60_000
                continue
            bars.append(
                {
                    "symbol": symbol,
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
                }
            )
            t += 60_000
        return bars

    def is_history_ready(self):
        return bool(self.ready), ""

    def should_backoff(self, now_ms: int) -> bool:
        return int(now_ms) < int(self.retry_after_ms)

    def note_not_ready(self, now_ms: int, reason: str) -> int:
        _ = reason
        if int(self.retry_after_ms) > int(now_ms):
            return int(self.retry_after_ms)
        self.retry_after_ms = int(now_ms) + 60_000
        return int(self.retry_after_ms)


def test_tail_guard_repair_flag_and_budget(tmp_path: Path, monkeypatch) -> None:
    freeze_time(monkeypatch)
    db = tmp_path / "test.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)

    config = Config(
        tail_guard_checked_ttl_s=300,
        tail_guard_safe_repair_only_when_market_closed=False,
    )
    calendar = Calendar([], config.calendar_tag)
    provider = BudgetProbeProvider(calendar=calendar)
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
    bars: List[Dict[str, Any]] = provider.fetch_1m_final("XAUUSD", start_ms, end_open_ms, limit=2000)
    for bar in bars:
        bar["ingest_ts_ms"] = now_ms
    store.upsert_1m_final("XAUUSD", bars)

    gap_open_ms = start_ms + 5 * 60_000
    conn = store.connect()
    try:
        conn.execute(
            "DELETE FROM bars_1m_final WHERE symbol = ? AND open_time_ms = ?",
            ("XAUUSD", gap_open_ms),
        )
        conn.commit()
    finally:
        conn.close()

    provider.calls = 0
    budget = DummyBudget()

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
        repair=False,
        republish_after_repair=False,
        republish_force=False,
        tfs=["1m"],
        history_budget=budget,
    )

    assert provider.calls == 0
    assert budget.acquired == 0
    assert budget.released == 0

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
        history_budget=budget,
    )

    assert provider.calls >= 1
    assert budget.acquired == budget.released
    assert budget.acquired >= 1
