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


def _build_status(config: Config) -> StatusManager:
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
    return status


def test_command_bus_drops_oversize_payload_before_json() -> None:
    config = Config(max_command_payload_bytes=16)
    status = _build_status(config)
    metrics = status.metrics
    assert metrics is not None

    bus = CommandBus(
        redis_client=None,
        config=config,
        validator=status.validator,
        status=status,
        metrics=metrics,
        allowlist={"ping"},
        handlers={"ping": lambda _payload: None},
    )

    bus.handle_raw_message("x" * 200)

    snapshot = status.snapshot()
    errors = snapshot.get("errors", [])
    assert errors
    last = errors[-1]
    assert last.get("code") == "command_payload_too_large"
    assert last.get("message") == "Перевищено ліміт"

    count = metrics.commands_dropped_total.labels(reason="payload_too_large")._value.get()
    assert count == 1


def test_command_bus_contract_error_redacted() -> None:
    config = Config()
    status = _build_status(config)
    metrics = status.metrics
    assert metrics is not None

    bus = CommandBus(
        redis_client=None,
        config=config,
        validator=status.validator,
        status=status,
        metrics=metrics,
        allowlist={"ping"},
        handlers={"ping": lambda _payload: None},
    )

    payload = {"cmd": "ping", "req_id": "req-1", "ts": 1, "args": {}, "extra": "x"}
    bus.handle_payload(payload)

    snapshot = status.snapshot()
    errors = snapshot.get("errors", [])
    assert errors
    last = errors[-1]
    assert last.get("code") == "contract_error"
    assert last.get("message") == "Некоректна команда"
    assert "Additional properties" not in str(last.get("message", ""))
    assert "additionalProperties" not in str(last.get("message", ""))
