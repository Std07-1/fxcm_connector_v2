from __future__ import annotations

from datetime import datetime, timezone

from core.time.calendar import Calendar
from core.time.timestamps import to_epoch_ms_utc


def _ms(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> int:
    return to_epoch_ms_utc(datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc))


def test_last_bar_before_daily_break() -> None:
    calendar = Calendar(calendar_tag="fxcm_calendar_v1_ny")
    ts_ms = _ms(2026, 1, 20, 21, 59, 30)
    break_start_ms = _ms(2026, 1, 20, 22, 0, 0)
    assert calendar.is_open(ts_ms) is True
    assert calendar.next_pause_ms(ts_ms) == break_start_ms


def test_first_bar_after_daily_break() -> None:
    calendar = Calendar(calendar_tag="fxcm_calendar_v1_ny")
    in_break_ms = _ms(2026, 1, 20, 22, 2, 0)
    break_end_ms = _ms(2026, 1, 20, 22, 5, 0)
    assert calendar.is_open(in_break_ms) is False
    assert calendar.next_open_ms(in_break_ms) == break_end_ms


def test_daily_break_last_first_bar_boundaries() -> None:
    calendar = Calendar(calendar_tag="fxcm_calendar_v1_ny")
    last_bar_open_ms = _ms(2026, 1, 20, 21, 59, 0)
    last_bar_close_ms = _ms(2026, 1, 20, 21, 59, 59) + 999
    break_start_ms = _ms(2026, 1, 20, 22, 0, 0)
    first_bar_open_ms = _ms(2026, 1, 20, 22, 5, 0)
    assert calendar.is_open(last_bar_open_ms) is True
    assert calendar.is_open(last_bar_close_ms) is True
    assert calendar.is_open(break_start_ms) is False
    assert calendar.next_pause_ms(last_bar_open_ms) == break_start_ms
    assert calendar.next_open_ms(break_start_ms) == first_bar_open_ms


def test_weekend_close_open_boundary() -> None:
    calendar = Calendar(calendar_tag="fxcm_calendar_v1_ny")
    saturday_ms = _ms(2026, 1, 24, 12, 0, 0)
    sunday_open_ms = _ms(2026, 1, 25, 22, 0, 0)
    assert calendar.is_open(saturday_ms) is False
    assert calendar.next_open_ms(saturday_ms) == sunday_open_ms


def test_dst_boundary_pre_dst_sunday_open_utc() -> None:
    calendar = Calendar(calendar_tag="fxcm_calendar_v1_ny")
    saturday_ms = _ms(2026, 2, 28, 12, 0, 0)
    sunday_open_ms = _ms(2026, 3, 1, 22, 0, 0)
    assert calendar.next_open_ms(saturday_ms) == sunday_open_ms


def test_dst_boundary_post_dst_sunday_open_utc() -> None:
    calendar = Calendar(calendar_tag="fxcm_calendar_v1_ny")
    saturday_ms = _ms(2026, 3, 14, 12, 0, 0)
    sunday_open_ms = _ms(2026, 3, 15, 21, 0, 0)
    assert calendar.next_open_ms(saturday_ms) == sunday_open_ms
