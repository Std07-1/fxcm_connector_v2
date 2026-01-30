from __future__ import annotations

from datetime import datetime, timezone

from core.time.buckets import TF_TO_MS, get_bucket_close_ms, get_bucket_open_ms
from core.time.calendar import Calendar


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_1d_boundary_22_utc() -> None:
    calendar = Calendar(calendar_tag="fxcm_calendar_v1_ny", overrides_path="config/calendar_overrides.json")
    ts_ms = _ms(datetime(2026, 1, 18, 21, 30, tzinfo=timezone.utc))
    open_ms = get_bucket_open_ms("1d", ts_ms, calendar)
    expected_open = _ms(datetime(2026, 1, 17, 22, 0, tzinfo=timezone.utc))
    assert open_ms == expected_open
    close_ms = get_bucket_close_ms("1d", open_ms, calendar)
    assert close_ms == open_ms + TF_TO_MS["1d"] - 1

    ts2_ms = _ms(datetime(2026, 1, 18, 22, 30, tzinfo=timezone.utc))
    open2_ms = get_bucket_open_ms("1d", ts2_ms, calendar)
    expected_open2 = _ms(datetime(2026, 1, 18, 22, 0, tzinfo=timezone.utc))
    assert open2_ms == expected_open2
