from __future__ import annotations

from datetime import datetime, timezone

from core.time.calendar import Calendar
from core.time.timestamps import to_epoch_ms_utc


def _ms(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> int:
    return to_epoch_ms_utc(datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc))


def test_next_open_xau_weekend_reopen_is_2301utc() -> None:
    calendar = Calendar(calendar_tag="fxcm_calendar_v1_utc_overrides")
    sunday_evening_ms = _ms(2026, 1, 25, 20, 6, 0)
    expected_open_ms = _ms(2026, 1, 25, 23, 1, 0)
    assert calendar.next_open_ms(sunday_evening_ms) == expected_open_ms


def test_next_open_xau_daily_break_reopen_is_2301utc() -> None:
    calendar = Calendar(calendar_tag="fxcm_calendar_v1_utc_overrides")
    in_break_ms = _ms(2026, 1, 20, 22, 6, 0)
    expected_open_ms = _ms(2026, 1, 20, 23, 1, 0)
    assert calendar.next_open_ms(in_break_ms) == expected_open_ms
