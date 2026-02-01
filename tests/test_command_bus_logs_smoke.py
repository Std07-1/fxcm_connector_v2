from __future__ import annotations

import logging
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


def test_command_bus_logs_smoke(caplog) -> None:
    config = Config()
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    metrics = create_metrics(CollectorRegistry())
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=InMemoryPublisher(),
        calendar=calendar,
        metrics=metrics,
    )
    status.build_initial_snapshot()

    def _handler(_payload: dict) -> None:
        return

    bus = CommandBus(
        redis_client=None,
        config=config,
        validator=validator,
        status=status,
        metrics=metrics,
        allowlist={"ping"},
        handlers={"ping": _handler},
    )

    caplog.set_level(logging.INFO, logger="command_bus")
    payload = {"cmd": "ping", "req_id": "req-1", "ts": 1, "args": {}}
    bus.handle_payload(payload)

    messages = [rec.message for rec in caplog.records]
    assert any("COMMAND start" in msg for msg in messages)
    assert any("COMMAND end" in msg for msg in messages)
