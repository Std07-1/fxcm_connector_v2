from __future__ import annotations

from pathlib import Path

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


def test_preview_status_updates() -> None:
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

    status.record_ohlcv_publish(tf="1m", bar_open_time_ms=1_736_980_000_000, publish_ts_ms=1_736_980_000_500)
    snapshot = status.snapshot()
    preview = snapshot.get("ohlcv_preview", {})
    assert preview.get("preview_total") == 1
    assert preview.get("last_bar_open_time_ms", {}).get("1m", 0) > 0
