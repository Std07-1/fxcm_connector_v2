from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.command_bus import CommandBus
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


class DummyStatusPublisher:
    def set_snapshot(self, key: str, json_str: str) -> None:
        return None

    def publish(self, channel: str, json_str: str) -> None:
        return None


def test_tail_guard_ssot_empty_loud_error(tmp_path: Path) -> None:
    root_dir = Path(__file__).resolve().parents[1]
    db = tmp_path / "test.sqlite"
    store = SQLiteStore(db_path=db)
    store.init_schema(root_dir / "store" / "schema.sql")

    config = Config()
    calendar = Calendar([], config.calendar_tag)
    validator = SchemaValidator(root_dir=root_dir)
    redis = DummyRedis()
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=DummyStatusPublisher(),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()
    derived_rebuilder = DerivedRebuildCoordinator()
    publisher = RedisPublisher(redis, config)

    def _handler(payload: dict) -> None:
        args = payload.get("args", {})
        symbol = str(args.get("symbols", ["XAUUSD"])[0])
        run_tail_guard(
            config=config,
            store=store,
            calendar=calendar,
            provider=None,
            redis_client=redis,
            derived_rebuilder=derived_rebuilder,
            publisher=publisher,
            validator=validator,
            status=status,
            metrics=None,
            symbol=symbol,
            window_hours=1,
            repair=False,
            republish_after_repair=False,
            republish_force=False,
            tfs=["1m"],
        )

    bus = CommandBus(
        redis_client=None,
        config=config,
        validator=validator,
        status=status,
        metrics=None,
        allowlist={"fxcm_tail_guard"},
        handlers={"fxcm_tail_guard": _handler},
    )

    bus.handle_payload(
        {
            "cmd": "fxcm_tail_guard",
            "req_id": "test-ssot-empty",
            "ts": 1_736_980_000_000,
            "args": {"symbols": ["XAUUSD"], "window_hours": 1},
        }
    )

    snap = status.snapshot()
    assert snap["last_command"]["cmd"] == "fxcm_tail_guard"
    assert any(err.get("code") == "ssot_empty" for err in snap.get("errors", []))
    tail = snap.get("tail_guard", {}).get("far", snap.get("tail_guard", {}))
    assert int(tail.get("last_audit_ts_ms", 0)) > 0
    assert tail.get("tf_states", {}).get("1m", {}).get("state") == "store_empty"
