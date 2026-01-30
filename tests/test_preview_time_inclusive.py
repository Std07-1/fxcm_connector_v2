from __future__ import annotations

from core.time.buckets import get_bucket_close_ms, get_bucket_open_ms


def test_preview_time_inclusive_1m() -> None:
    ts_ms = 1_736_980_000_000
    open_ms = get_bucket_open_ms("1m", ts_ms, None)
    close_ms = get_bucket_close_ms("1m", open_ms, None)
    assert close_ms == open_ms + 60_000 - 1
