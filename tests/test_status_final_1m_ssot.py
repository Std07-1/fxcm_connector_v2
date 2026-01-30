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


def test_status_final_1m_ssot() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    config = Config()
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

    status.record_final_publish(
        last_complete_bar_ms=1_736_980_019_999,
        now_ms=1_736_980_020_000,
        lookback_days=2,
        bars_total_est=456,
    )

    snapshot = status.snapshot()
    final_1m = snapshot.get("ohlcv_final_1m", {})
    final_map = snapshot.get("ohlcv_final", {}).get("1m", {})
    assert int(final_1m.get("last_complete_bar_ms", 0)) == 1_736_980_019_999
    assert int(final_map.get("last_complete_bar_ms", 0)) == 1_736_980_019_999
    assert int(final_1m.get("bars_total_est", 0)) == 456
    assert int(final_map.get("bars_total_est", 0)) == 456
