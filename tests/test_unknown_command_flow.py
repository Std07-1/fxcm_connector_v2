from __future__ import annotations

from pathlib import Path
from typing import Optional

from prometheus_client import CollectorRegistry

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from observability.metrics import create_metrics
from runtime.command_bus import CommandBus
from runtime.status import StatusManager


class InMemoryPublisher:
    def __init__(self) -> None:
        self.last_snapshot: Optional[str] = None
        self.last_channel: Optional[str] = None

    def set_snapshot(self, key: str, json_str: str) -> None:
        self.last_snapshot = json_str

    def publish(self, channel: str, json_str: str) -> None:
        self.last_channel = channel


def test_unknown_command_updates_status() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    config = Config()
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    metrics = create_metrics(CollectorRegistry())
    publisher = InMemoryPublisher()
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=publisher,
        calendar=calendar,
        metrics=metrics,
    )
    status.build_initial_snapshot()

    bus = CommandBus(
        redis_client=None,
        config=config,
        validator=validator,
        status=status,
        metrics=metrics,
        allowlist=set(),
    )

    payload = {"cmd": "does_not_exist", "req_id": "req-0001", "ts": 1, "args": {}}
    bus.handle_payload(payload)

    snapshot = status.snapshot()
    assert snapshot["last_command"]["state"] == "error"
    assert snapshot["last_command"]["cmd"] == "does_not_exist"
    assert snapshot["last_command"]["req_id"] == "req-0001"
    assert any(err["code"] == "unknown_command" for err in snapshot["errors"])
