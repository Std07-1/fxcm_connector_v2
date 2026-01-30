from __future__ import annotations

from datetime import datetime, timezone
from typing import Tuple

from core.time.calendar import Calendar
from core.time.timestamps import to_epoch_ms_utc


def _ms(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> int:
    return to_epoch_ms_utc(datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc))


def run() -> Tuple[bool, str]:
    calendar = Calendar(calendar_tag="fxcm_calendar_v1_ny")
    ts_ms = _ms(2026, 1, 20, 21, 59, 30)
    break_start_ms = _ms(2026, 1, 20, 22, 0, 0)
    if not calendar.is_open(ts_ms):
        return False, "FAIL: очікувалось trading_time перед daily break"
    if calendar.next_pause_ms(ts_ms) != break_start_ms:
        return False, "FAIL: next_trading_pause має збігатися з daily break start"

    in_break_ms = _ms(2026, 1, 20, 22, 2, 0)
    break_end_ms = _ms(2026, 1, 20, 22, 5, 0)
    if calendar.is_open(in_break_ms):
        return False, "FAIL: очікувалось CLOSED під час daily break"
    if calendar.next_open_ms(in_break_ms) != break_end_ms:
        return False, "FAIL: next_trading_open має збігатися з daily break end"

    saturday_ms = _ms(2026, 1, 24, 12, 0, 0)
    sunday_open_ms = _ms(2026, 1, 25, 22, 0, 0)
    if calendar.is_open(saturday_ms):
        return False, "FAIL: очікувалось CLOSED у суботу"
    if calendar.next_open_ms(saturday_ms) != sunday_open_ms:
        return False, "FAIL: next_trading_open має збігатися з Sunday open"

    pre_dst_saturday = _ms(2026, 2, 28, 12, 0, 0)
    pre_dst_open = _ms(2026, 3, 1, 22, 0, 0)
    if calendar.next_open_ms(pre_dst_saturday) != pre_dst_open:
        return False, "FAIL: DST (до переходу) має давати Sunday 22:00 UTC"

    post_dst_saturday = _ms(2026, 3, 14, 12, 0, 0)
    post_dst_open = _ms(2026, 3, 15, 21, 0, 0)
    if calendar.next_open_ms(post_dst_saturday) != post_dst_open:
        return False, "FAIL: DST (після переходу) має давати Sunday 21:00 UTC"
    if pre_dst_open == post_dst_open:
        return False, "FAIL: DST boundary має змінювати UTC-час для Sunday open"

    return True, "OK: календарні межі (daily break + weekend) узгоджені"
