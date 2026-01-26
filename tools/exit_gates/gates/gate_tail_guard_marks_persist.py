from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

from config.config import Config
from core.time.calendar import Calendar
from core.time.timestamps import to_epoch_ms_utc
from core.validation.validator import SchemaValidator
from observability.metrics import create_metrics
from runtime.publisher import RedisPublisher
from runtime.rebuild_derived import DerivedRebuildCoordinator
from runtime.status import StatusManager
from runtime.tail_guard import run_tail_guard
from store.sqlite_store import SQLiteStore


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


def run() -> Tuple[bool, str]:
    fixed_now_ms = to_epoch_ms_utc(datetime(2026, 1, 20, 17, 0, tzinfo=timezone.utc))
    original_time = time.time
    time.time = lambda: fixed_now_ms / 1000.0
    try:
        root_dir = Path(__file__).resolve().parents[3]
        db_path = Path(root_dir) / "data" / "_gate_tail_guard_marks.sqlite"
        if db_path.exists():
            db_path.unlink()
        store = SQLiteStore(db_path=db_path)
        store.init_schema(Path(root_dir) / "store" / "schema.sql")

        config = Config(tail_guard_checked_ttl_s=300)
        calendar = Calendar([], config.calendar_tag)
        metrics = create_metrics()
        validator = SchemaValidator(root_dir=root_dir)
        redis = DummyRedis()
        publisher = RedisPublisher(redis, config)
        status = StatusManager(
            config=config,
            validator=validator,
            publisher=publisher,
            calendar=calendar,
            metrics=metrics,
        )
        status.build_initial_snapshot()
        derived_rebuilder = DerivedRebuildCoordinator()

        now_ms = int(time.time() * 1000)
        end_open_ms = now_ms - (now_ms % 60_000) - 60_000
        start_open_ms = end_open_ms - (60 - 1) * 60_000
        bars = []
        t = start_open_ms
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

        first = run_tail_guard(
            config=config,
            store=store,
            calendar=calendar,
            provider=None,
            redis_client=redis,
            derived_rebuilder=derived_rebuilder,
            publisher=publisher,
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
        if first.tf_states["1m"].status != "ok":
            return False, "tail_guard первинний audit не ok"

        second = run_tail_guard(
            config=config,
            store=store,
            calendar=calendar,
            provider=None,
            redis_client=redis,
            derived_rebuilder=derived_rebuilder,
            publisher=publisher,
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
        if second.tf_states["1m"].skipped_by_ttl is not True:
            return False, "очікував skip за marks"

        updated = dict(bars[-1])
        updated["close"] = 1.5
        updated["ingest_ts_ms"] = now_ms + 1
        store.upsert_1m_final("XAUUSD", [updated])

        third = run_tail_guard(
            config=config,
            store=store,
            calendar=calendar,
            provider=None,
            redis_client=redis,
            derived_rebuilder=derived_rebuilder,
            publisher=publisher,
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
        if third.tf_states["1m"].skipped_by_ttl is True:
            return False, "invalidation не спрацювала"

        return True, "OK: tail_guard marks persist/invalidate"
    finally:
        time.time = original_time
