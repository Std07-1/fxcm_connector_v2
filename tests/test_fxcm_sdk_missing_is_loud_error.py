from __future__ import annotations

from pathlib import Path

import pytest

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime import fxcm_forexconnect
from runtime.status import StatusManager


class _DummyPublisher:
    def set_snapshot(self, key: str, json_str: str) -> None:
        return None

    def publish(self, channel: str, json_str: str) -> None:
        return None


def test_fxcm_sdk_missing_is_loud_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fxcm_forexconnect, "_try_import_forexconnect", lambda: (None, "missing"))
    config = Config(
        fxcm_backend="forexconnect",
        fxcm_username="demo",
        fxcm_password="demo",
    )
    calendar = Calendar([], config.calendar_tag)
    validator = SchemaValidator(root_dir=Path(__file__).resolve().parents[1])
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=_DummyPublisher(),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()
    ok = fxcm_forexconnect.ensure_fxcm_ready(config, status)
    assert ok is False
    snap = status.snapshot()
    assert snap["fxcm"]["state"] == "error"
    codes = [err.get("code") for err in snap.get("errors", [])]
    assert "fxcm_sdk_missing" in codes
