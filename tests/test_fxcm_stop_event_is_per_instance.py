from __future__ import annotations

from pathlib import Path

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.fxcm_forexconnect import FxcmForexConnectStream
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager


class _DummyRedis:
    def publish(self, channel: str, payload: str) -> None:
        return None

    def set(self, key: str, value: str) -> None:
        return None


def _build_status() -> StatusManager:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    config = Config()
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    publisher = RedisPublisher(_DummyRedis(), config)
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=publisher,
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()
    return status


def test_fxcm_stop_event_is_per_instance() -> None:
    config = Config()
    status = _build_status()

    stream_a = FxcmForexConnectStream(config=config, status=status, on_tick=lambda *_: None)
    stream_b = FxcmForexConnectStream(config=config, status=status, on_tick=lambda *_: None)

    assert stream_a._stop_event is not stream_b._stop_event
