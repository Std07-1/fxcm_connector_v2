from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from prometheus_client import CollectorRegistry

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from observability.metrics import create_metrics
from runtime.command_bus import CommandBus
from runtime.status import StatusManager


class FakePubSub:
    def __init__(self) -> None:
        self.subscribed_channel: Optional[str] = None
        self.closed = False

    def subscribe(self, channel: str) -> None:
        self.subscribed_channel = channel

    def get_message(self, timeout: float = 0.0) -> None:
        time.sleep(min(0.05, timeout))
        return None

    def close(self) -> None:
        self.closed = True


class FakeRedis:
    def __init__(self) -> None:
        self._pubsub = FakePubSub()

    def pubsub(self, ignore_subscribe_messages: bool = True) -> FakePubSub:
        return self._pubsub


def test_command_bus_starts_and_updates_status() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    config = Config(command_bus_heartbeat_period_s=1)
    calendar = Calendar([], config.calendar_tag)
    metrics = create_metrics(CollectorRegistry())
    publisher = _InMemoryPublisher()
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=publisher,
        calendar=calendar,
        metrics=metrics,
    )
    status.build_initial_snapshot()

    bus = CommandBus(
        redis_client=FakeRedis(),
        config=config,
        validator=validator,
        status=status,
        metrics=metrics,
        allowlist=set(),
    )

    started = bus.start()
    assert started is True
    time.sleep(0.1)

    snapshot = status.snapshot()
    command_bus = snapshot["command_bus"]
    assert command_bus["state"] == "running"
    assert int(command_bus["last_heartbeat_ts_ms"]) > 0

    bus.stop()


class _InMemoryPublisher:
    def __init__(self) -> None:
        self.last_snapshot: Optional[str] = None
        self.last_channel: Optional[str] = None

    def set_snapshot(self, key: str, json_str: str) -> None:
        self.last_snapshot = json_str

    def publish(self, channel: str, json_str: str) -> None:
        self.last_channel = channel
