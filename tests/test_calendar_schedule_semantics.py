from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.time.sessions import TradingCalendar, load_calendar_overrides
from core.time.timestamps import to_epoch_ms_utc


def _ms(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> int:
    return to_epoch_ms_utc(datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc))


@pytest.mark.parametrize(
    "tag,break_before_ms,break_during_ms,after_close_ms,after_open_ms",
    [
        (
            "fxcm_calendar_v1_ny",
            _ms(2026, 1, 7, 21, 59, 0),
            _ms(2026, 1, 7, 22, 1, 0),
            _ms(2026, 1, 9, 22, 1, 0),
            _ms(2026, 1, 11, 22, 1, 0),
        ),
        (
            "fxcm_calendar_v1_utc_overrides",
            _ms(2026, 1, 7, 21, 59, 0),
            _ms(2026, 1, 7, 22, 1, 0),
            _ms(2026, 1, 9, 21, 46, 0),
            _ms(2026, 1, 11, 23, 2, 0),
        ),
    ],
)
def test_calendar_schedule_semantics(
    tag: str,
    break_before_ms: int,
    break_during_ms: int,
    after_close_ms: int,
    after_open_ms: int,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    overrides = load_calendar_overrides(repo_root=repo_root, tag=tag)
    calendar = TradingCalendar([], tag, overrides=overrides)

    assert calendar.is_trading_time(break_before_ms) is True
    assert calendar.is_trading_time(break_during_ms) is False
    assert calendar.is_trading_time(after_close_ms) is False
    assert calendar.is_trading_time(after_open_ms) is True
