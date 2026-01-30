from __future__ import annotations

from pathlib import Path

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.status import StatusManager


class _DummyPublisher:
    def set_snapshot(self, key: str, json_str: str) -> None:
        return None

    def publish(self, channel: str, json_str: str) -> None:
        return None


def test_fxcm_disabled_by_default() -> None:
    config = Config()
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    validator = SchemaValidator(root_dir=Path(__file__).resolve().parents[1])
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=_DummyPublisher(),
        calendar=calendar,
        metrics=None,
    )
    snap = status.build_initial_snapshot()
    assert snap["fxcm"]["state"] == "connecting"
