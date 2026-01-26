from __future__ import annotations

import time
from pathlib import Path

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager
from runtime.tick_feed import TickPublisher


class _DummyRedis:
    def __init__(self) -> None:
        self.last_channel = ""
        self.last_payload = ""

    def publish(self, channel: str, payload: str) -> None:
        self.last_channel = channel
        self.last_payload = payload

    def set(self, key: str, value: str) -> None:
        return None


def test_tick_publisher_updates_status() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    config = Config(tick_mode="off")
    calendar = Calendar(
        closed_intervals_utc=config.closed_intervals_utc,
        calendar_tag=config.calendar_tag,
    )
    redis_client = _DummyRedis()
    publisher = RedisPublisher(redis_client, config)
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=publisher,
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    tick_publisher = TickPublisher(
        config=config,
        publisher=publisher,
        validator=validator,
        status=status,
    )
    now_ms = int(time.time() * 1000)
    tick_ts_ms = now_ms - 500
    tick_publisher.publish_tick(
        symbol="XAUUSD",
        bid=1.0,
        ask=1.2,
        mid=1.1,
        tick_ts_ms=tick_ts_ms,
        snap_ts_ms=now_ms,
    )

    snapshot = status.snapshot()
    price = snapshot.get("price", {})
    assert price.get("tick_total") == 1
    assert price.get("last_tick_ts_ms") == tick_ts_ms
    assert price.get("last_tick_event_ms") == tick_ts_ms
    assert price.get("last_tick_snap_ms") == now_ms
    assert price.get("tick_skew_ms") == 500
    assert price.get("tick_skew_ms", 0) >= 0
