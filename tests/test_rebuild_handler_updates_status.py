from __future__ import annotations

import tempfile
from pathlib import Path

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.handlers_p4 import handle_rebuild_derived_command
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager
from store.bars_store import BarsStoreSQLite
from store.sqlite_store import SQLiteStore


class _DummyRedis:
    def publish(self, channel: str, payload: str) -> None:
        return None

    def set(self, key: str, value: str) -> None:
        return None


def test_rebuild_handler_updates_status() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    config = Config()
    calendar = Calendar(
        closed_intervals_utc=config.closed_intervals_utc,
        calendar_tag=config.calendar_tag,
    )
    validator = SchemaValidator(root_dir=root_dir)
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=RedisPublisher(_DummyRedis(), config),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "bars.sqlite"
        store = SQLiteStore(db_path=db_path)
        store.init_schema(root_dir / "store" / "schema.sql")

        base = 1_736_980_000_000
        open_start = base - (base % 900_000)
        bars = []
        for i in range(15):
            open_time = open_start + i * 60_000
            close_time = open_time + 60_000 - 1
            bars.append(
                {
                    "symbol": "XAUUSD",
                    "open_time_ms": open_time,
                    "close_time_ms": close_time,
                    "open": 2000.0 + i,
                    "high": 2001.0 + i,
                    "low": 1999.0 + i,
                    "close": 2000.5 + i,
                    "volume": 1.0,
                    "complete": 1,
                    "synthetic": 0,
                    "source": "history",
                    "event_ts_ms": close_time,
                    "ingest_ts_ms": close_time,
                }
            )
        store.upsert_1m_final("XAUUSD", bars)

        bars_store = BarsStoreSQLite(db_path=db_path, schema_path=root_dir / "store" / "schema.sql")
        payload = {
            "cmd": "fxcm_rebuild_derived",
            "req_id": "test-p4-0001",
            "ts": 1_736_980_000_000,
            "args": {"symbol": "XAUUSD", "window_hours": 1, "tfs": ["15m"]},
        }
        handle_rebuild_derived_command(
            payload=payload,
            config=config,
            bars_store=bars_store,
            publisher=RedisPublisher(_DummyRedis(), config),
            validator=validator,
            status=status,
            metrics=None,
        )

    snapshot = status.snapshot()
    derived = snapshot.get("derived_rebuild", {})
    assert derived.get("state") == "ok"
