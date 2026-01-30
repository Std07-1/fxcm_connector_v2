from __future__ import annotations

from pathlib import Path

from app.composition import build_history_provider_for_runtime
from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager


class _DummyRedis:
    def publish(self, channel: str, payload: str) -> None:
        return None

    def set(self, key: str, value: str) -> None:
        return None


def test_history_provider_configured() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    config = Config(history_provider_kind="fxcm_forexconnect")
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    validator = SchemaValidator(root_dir=root_dir)
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=RedisPublisher(_DummyRedis(), config),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    provider = build_history_provider_for_runtime(config=config, status=status, metrics=None)
    assert provider is not None
