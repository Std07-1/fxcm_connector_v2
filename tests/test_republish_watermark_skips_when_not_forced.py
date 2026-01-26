from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
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


def test_republish_watermark_skips_when_not_forced(tmp_path: Path) -> None:
    db = tmp_path / "test.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)

    config = Config(republish_watermark_ttl_s=300)
    redis = DummyRedis()
    status = StatusManager(
        config=config,
        validator=SchemaValidator(root_dir=Path(__file__).resolve().parents[1]),
        publisher=RedisPublisher(redis, config),
        calendar=Calendar([], config.calendar_tag),
        metrics=None,
    )
    status.build_initial_snapshot()

    key = f"{config.ns}:internal:republish_watermark:XAUUSD:1m:24"
    redis.setex(key, 300, "1")

    republish_tail(
        config=config,
        store=store,
        redis_client=redis,
        publisher=RedisPublisher(redis, config),
        validator=SchemaValidator(root_dir=Path(__file__).resolve().parents[1]),
        status=status,
        metrics=None,
        symbol="XAUUSD",
        timeframes=["1m"],
        window_hours=24,
        force=False,
        req_id="test-3",
    )

    snap = status.snapshot()
    assert snap["republish"]["skipped_by_watermark"] is True
    assert snap["republish"]["state"] == "skipped"
