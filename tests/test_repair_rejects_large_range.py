from __future__ import annotations

from pathlib import Path

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.publisher import RedisPublisher
from runtime.repair import repair_missing_1m
from runtime.status import StatusManager
from store.sqlite_store import SQLiteStore
from tests.fixtures.sim.history_sim_provider import HistorySimProvider
from tests.time_helpers import TEST_NOW_MS, freeze_time


class DummyRedis:
    def publish(self, channel: str, value: str) -> None:
        return None

    def set(self, key: str, value: str) -> None:
        return None


def test_repair_rejects_large_range(tmp_path: Path, monkeypatch) -> None:
    freeze_time(monkeypatch)
    db = tmp_path / "test.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)

    config = Config(tail_guard_repair_max_gap_minutes=10)
    calendar = Calendar([], config.calendar_tag)
    provider = HistorySimProvider(calendar=calendar)
    status = StatusManager(
        config=config,
        validator=SchemaValidator(root_dir=Path(__file__).resolve().parents[1]),
        publisher=RedisPublisher(DummyRedis(), config),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    now_ms = TEST_NOW_MS
    start_ms = now_ms - 20 * 60_000
    end_ms = now_ms
    try:
        repair_missing_1m(
            config=config,
            store=store,
            provider=provider,
            calendar=calendar,
            status=status,
            metrics=None,
            symbol="XAUUSD",
            ranges=[(start_ms, end_ms)],
            max_gap_minutes=config.tail_guard_repair_max_gap_minutes,
        )
    except ValueError:
        pass
    errors = status.snapshot().get("errors", [])
    assert any(err.get("code") == "repair_range_too_large" for err in errors)
