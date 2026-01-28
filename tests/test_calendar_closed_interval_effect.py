from __future__ import annotations

from datetime import datetime, timezone

from core.time.sessions import CalendarOverrides, TradingCalendar
from core.time.timestamps import to_epoch_ms_utc


def _ms(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> int:
    return to_epoch_ms_utc(datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc))


def test_calendar_closed_interval_blocks_trading_time() -> None:
    closed = [(_ms(2026, 1, 5, 10, 0), _ms(2026, 1, 5, 11, 0))]
    overrides = CalendarOverrides(
        calendar_tag="fxcm_calendar_v1_utc_overrides",
        tz_name="UTC",
        weekly_open="23:01",
        weekly_close="21:45",
        daily_break_start="22:00",
        daily_break_minutes=61,
        closed_intervals_utc=closed,
    )
    calendar = TradingCalendar([], "fxcm_calendar_v1_utc_overrides", overrides=overrides)
    inside = _ms(2026, 1, 5, 10, 30)
    after = _ms(2026, 1, 5, 11, 1)
    assert calendar.is_trading_time(inside) is False
    assert calendar.is_trading_time(after) is True
