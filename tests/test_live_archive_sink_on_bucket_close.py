from __future__ import annotations

from runtime.ohlcv_preview import select_closed_bars_for_archive


def test_select_closed_bars_only_on_transition() -> None:
    bars = [
        {"open_time": 0, "close_time": 59_999},
        {"open_time": 60_000, "close_time": 119_999},
    ]
    closed = select_closed_bars_for_archive(bars, last_archived_open_ms=-1)
    assert len(closed) == 1
    assert int(closed[0]["open_time"]) == 0

    closed_none = select_closed_bars_for_archive(bars=[bars[-1]], last_archived_open_ms=60_000)
    assert closed_none == []
