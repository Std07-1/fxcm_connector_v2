from __future__ import annotations

from pathlib import Path
from typing import Tuple

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.repair import repair_missing_1m
from runtime.status import StatusManager
from store.sqlite_store import SQLiteStore
from tests.fixtures.sim.history_sim_provider import HistorySimProvider


class _DummyPublisher:
    def set_snapshot(self, key: str, json_str: str) -> None:
        return None

    def publish(self, channel: str, json_str: str) -> None:
        return None


def run() -> Tuple[bool, str]:
    root_dir = Path(__file__).resolve().parents[3]
    config = Config(
        tail_guard_repair_max_missing_bars=1,
        tail_guard_repair_max_window_ms=60_000,
        tail_guard_repair_max_history_chunks=1,
    )
    calendar = Calendar([], config.calendar_tag)
    validator = SchemaValidator(root_dir=root_dir)
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=_DummyPublisher(),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    db = Path(root_dir) / "data" / "_gate_tail_guard_repair.sqlite"
    if db.exists():
        db.unlink()
    store = SQLiteStore(db_path=db)
    store.init_schema(Path(root_dir) / "store" / "schema.sql")
    provider = HistorySimProvider(calendar=calendar)

    ranges = [(1_736_980_000_000, 1_736_980_000_000 + 5 * 60_000 - 1)]
    try:
        repair_missing_1m(
            config=config,
            store=store,
            provider=provider,
            calendar=calendar,
            status=status,
            metrics=None,
            symbol="XAUUSD",
            ranges=ranges,
            max_gap_minutes=10,
        )
    except ValueError:
        errors = status.snapshot().get("errors", [])
        if any(err.get("code") == "repair_budget_exceeded" for err in errors):
            return True, "OK: repair budget exceeded"
        return False, "очікував code=repair_budget_exceeded"
    return False, "repair budget не спрацював"
