from __future__ import annotations

import time
from pathlib import Path

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from observability.metrics import create_metrics
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager
from runtime.tick_feed import TickPublisher


class _DummyRedis:
    def __init__(self) -> None:
        self.publish_count = 0
        self.last_channel = ""
        self.last_payload = ""

    def publish(self, channel: str, payload: str) -> None:
        self.publish_count += 1
        self.last_channel = channel
        self.last_payload = payload

    def set(self, _key: str, _value: str) -> None:
        return None


def test_tick_out_of_order_policy() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    config = Config(tick_mode="off")
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    redis_client = _DummyRedis()
    publisher = RedisPublisher(redis_client, config)
    metrics = create_metrics()
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=publisher,
        calendar=calendar,
        metrics=metrics,
    )
    status.build_initial_snapshot()

    tick_publisher = TickPublisher(
        config=config,
        publisher=publisher,
        validator=validator,
        status=status,
        metrics=metrics,
    )

    now_ms = int(time.time() * 1000)
    bucket_open = (now_ms // 60_000) * 60_000

    tick_publisher.publish_tick(
        symbol="XAUUSD",
        bid=1.0,
        ask=1.2,
        mid=1.1,
        tick_ts_ms=bucket_open + 1_000,
        snap_ts_ms=bucket_open + 1_000,
    )

    tick_publisher.publish_tick(
        symbol="XAUUSD",
        bid=1.0,
        ask=1.2,
        mid=1.1,
        tick_ts_ms=bucket_open - 1_000,
        snap_ts_ms=bucket_open + 2_000,
    )

    tick_publisher.publish_tick(
        symbol="XAUUSD",
        bid=1.0,
        ask=1.2,
        mid=1.1,
        tick_ts_ms=bucket_open - 61_000,
        snap_ts_ms=bucket_open + 3_000,
    )

    assert redis_client.publish_count == 1

    snapshot = status.snapshot()
    assert "tick_out_of_order" in snapshot.get("degraded", [])
    errors = snapshot.get("errors", [])
    event_errors = [err for err in errors if isinstance(err, dict) and err.get("code") == "tick_out_of_order"]
    assert len(event_errors) <= 1

    count = metrics.tick_out_of_order_total.labels(symbol="XAUUSD")._value.get()
    assert int(count) == 2
