from __future__ import annotations

from pathlib import Path
from typing import Optional

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.status import StatusManager


class InMemoryPublisher:
    def __init__(self) -> None:
        self.last_snapshot: Optional[str] = None
        self.last_channel: Optional[str] = None

    def set_snapshot(self, key: str, json_str: str) -> None:
        self.last_snapshot = json_str

    def publish(self, channel: str, json_str: str) -> None:
        self.last_channel = channel


def test_bootstrap_sequence_records_status_steps() -> None:
    config = Config()
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=InMemoryPublisher(),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    status.record_bootstrap_step(step="bootstrap", state="running")
    status.record_bootstrap_step(step="warmup", state="ok")
    status.record_bootstrap_step(step="republish_tail", state="ok")
    status.record_bootstrap_step(step="bootstrap", state="ok")

    snapshot = status.snapshot()
    bootstrap = snapshot.get("bootstrap", {})
    assert bootstrap.get("state") == "ok"
    assert bootstrap.get("step") == "bootstrap"
    assert int(bootstrap.get("last_step_ts_ms", 0)) > 0
