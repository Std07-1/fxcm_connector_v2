from __future__ import annotations

from datetime import datetime, timezone
from typing import Tuple

from core.time.calendar import Calendar
from core.time.timestamps import to_epoch_ms_utc


def _ms(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> int:
    return to_epoch_ms_utc(datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc))


def run() -> Tuple[bool, str]:
    calendar = Calendar([], "fxcm_calendar_v1_ny")
    sunday_evening_ms = _ms(2026, 1, 25, 20, 6, 0)
    expected_open_ms = _ms(2026, 1, 25, 23, 0, 0)
    actual = calendar.next_open_ms(sunday_evening_ms, symbol="XAUUSD")
    if actual != expected_open_ms:
        return False, f"очікував 23:00 UTC, отримав {actual}"
    return True, "OK: XAU next_open 23:00 UTC"
