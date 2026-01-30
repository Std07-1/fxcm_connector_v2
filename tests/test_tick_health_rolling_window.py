from __future__ import annotations

from pathlib import Path

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager


class _DummyRedis:
    def publish(self, channel: str, payload: str) -> None:
        _ = channel
        _ = payload

    def set(self, key: str, value: str) -> None:
        _ = key
        _ = value


def _make_status() -> StatusManager:
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
    return status


def test_tick_health_enters_degraded_on_high_drop_rate() -> None:
    status = _make_status()
    base_ms = 1_700_000_000_000
    for i in range(6):
        status.record_tick_drop_missing_event(now_ms=base_ms + i * 1000)
    for i in range(4):
        now_ms = base_ms + (6 + i) * 1000
        status.record_tick(tick_ts_ms=now_ms - 1, snap_ts_ms=now_ms, now_ms=now_ms)

    snapshot = status.snapshot()
    degraded = snapshot.get("degraded", [])
    assert "tick_event_time_unavailable" in degraded
    assert status.is_preview_paused() is True


def test_tick_health_exits_degraded_on_low_drop_rate() -> None:
    status = _make_status()
    base_ms = 1_700_000_000_000
    for i in range(6):
        status.record_tick_drop_missing_event(now_ms=base_ms + i * 1000)
    for i in range(4):
        now_ms = base_ms + (6 + i) * 1000
        status.record_tick(tick_ts_ms=now_ms - 1, snap_ts_ms=now_ms, now_ms=now_ms)

    now_ms = base_ms + 61_000
    for i in range(10):
        ts = now_ms + i * 1000
        status.record_tick(tick_ts_ms=ts - 1, snap_ts_ms=ts, now_ms=ts)

    snapshot = status.snapshot()
    degraded = snapshot.get("degraded", [])
    assert "tick_event_time_unavailable" not in degraded
    assert status.is_preview_paused() is False
