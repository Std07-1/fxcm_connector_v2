from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from observability.metrics import create_metrics
from runtime.publisher import RedisPublisher
from runtime.republish import republish_tail
from runtime.status import StatusManager
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


def test_republish_watermark_skip(tmp_path: Path) -> None:
    db = tmp_path / "test.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)

    config = Config(republish_watermark_ttl_s=300)
    validator = SchemaValidator(root_dir=Path(__file__).resolve().parents[1])
    metrics = create_metrics()
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=DummyStatusPublisher(),
        calendar=Calendar([], config.calendar_tag),
        metrics=metrics,
    )
    status.build_initial_snapshot()

    redis = DummyRedis()
    publisher = RedisPublisher(redis, config)
    republish_tail(
        config=config,
        store=store,
        redis_client=redis,
        publisher=publisher,
        validator=validator,
        status=status,
        metrics=metrics,
        symbol="XAUUSD",
        timeframes=["1m"],
        window_hours=24,
        force=False,
        req_id="test",
    )

    snap = status.snapshot()
    assert snap["republish"]["skipped_by_watermark"] is False

    republish_tail(
        config=config,
        store=store,
        redis_client=redis,
        publisher=publisher,
        validator=validator,
        status=status,
        metrics=metrics,
        symbol="XAUUSD",
        timeframes=["1m"],
        window_hours=24,
        force=False,
        req_id="test-2",
    )

    snap = status.snapshot()
    assert snap["republish"]["skipped_by_watermark"] is True
    assert snap["republish"]["state"] == "skipped"
