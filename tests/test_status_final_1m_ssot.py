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


class _DummyStore:
    def get_last_complete_close_ms(self, symbol: str) -> int:
        return 1_736_980_019_999

    def count_1m_final(self, symbol: str) -> int:
        return 456


def test_status_final_1m_ssot() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    config = Config()
    calendar = Calendar(
        closed_intervals_utc=config.closed_intervals_utc,
        calendar_tag=config.calendar_tag,
    )
    validator = SchemaValidator(root_dir=root_dir)
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=RedisPublisher(_DummyRedis(), config),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    status.sync_final_1m_from_store(
        store=_DummyStore(),
        symbol="XAUUSD",
        lookback_days=2,
        now_ms=1_736_980_020_000,
    )

    snapshot = status.snapshot()
    final_1m = snapshot.get("ohlcv_final_1m", {})
    final_map = snapshot.get("ohlcv_final", {}).get("1m", {})
    assert int(final_1m.get("last_complete_bar_ms", 0)) == 1_736_980_019_999
    assert int(final_map.get("last_complete_bar_ms", 0)) == 1_736_980_019_999
    assert int(final_1m.get("bars_total_est", 0)) == 456
    assert int(final_map.get("bars_total_est", 0)) == 456
