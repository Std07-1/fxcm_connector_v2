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


def test_raw_rate_limit_drops_without_json_parse() -> None:
    config = Config(
        command_rate_limit_enable=True,
        command_rate_limit_raw_per_s=1,
        command_rate_limit_raw_burst=1,
        command_coalesce_enable=True,
        command_coalesce_window_s=60,
    )
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

    bus.handle_raw_message('{"cmd":"ping","req_id":"r1","ts":1,"args":{}}')
    bus.handle_raw_message("not-json")

    snapshot = status.snapshot()
    errors = snapshot.get("errors", [])
    assert errors
    last = errors[-1]
    assert last.get("code") == "rate_limited"

    raw_limited = metrics.commands_rate_limited_total.labels(scope="raw")._value.get()
    assert raw_limited == 1


def test_contract_error_coalesced_not_spamming_status() -> None:
    config = Config(
        command_coalesce_enable=True,
        command_coalesce_window_s=60,
    )
    status = _build_status(config)

    bus = CommandBus(
        redis_client=None,
        config=config,
        validator=status.validator,
        status=status,
        metrics=status.metrics,
        allowlist={"ping"},
        handlers={"ping": lambda _payload: None},
    )

    for i in range(100):
        payload = {"cmd": "ping", "req_id": f"r{i}", "ts": 1, "args": {}, "extra": "x"}
        bus.handle_payload(payload)

    errors = status.snapshot().get("errors", [])
    contract_errors = [err for err in errors if isinstance(err, dict) and err.get("code") == "contract_error"]
    assert len(contract_errors) == 1


def test_heavy_command_collapse_to_latest() -> None:
    config = Config(
        command_heavy_collapse_enable=True,
        command_heavy_cmds=["backfill"],
        command_coalesce_enable=True,
        command_coalesce_window_s=60,
    )
    status = _build_status(config)

    calls = []

    def _handler(payload: dict) -> None:
        calls.append(payload.get("req_id"))
        if payload.get("req_id") == "req-0":
            for i in range(1, 11):
                bus.handle_payload({"cmd": "backfill", "req_id": f"req-{i}", "ts": i, "args": {}})

    bus = CommandBus(
        redis_client=None,
        config=config,
        validator=status.validator,
        status=status,
        metrics=status.metrics,
        allowlist={"backfill"},
        handlers={"backfill": _handler},
    )

    bus.handle_payload({"cmd": "backfill", "req_id": "req-0", "ts": 0, "args": {}})

    assert calls == ["req-0", "req-10"]
