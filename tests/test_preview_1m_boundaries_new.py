from __future__ import annotations

from core.market.preview_1m_builder import Preview1mBuilder
from core.market.tick import Tick


def test_preview_1m_boundaries() -> None:
    builder = Preview1mBuilder()
    tick_ts_ms = 1_700_000_123_456
    open_time = (tick_ts_ms // 60_000) * 60_000
    close_time = open_time + 60_000 - 1

    state = builder.on_tick(
        Tick(
            symbol="XAUUSD",
            bid=2000.0,
            ask=2000.2,
            mid=2000.1,
            tick_ts_ms=tick_ts_ms,
            snap_ts_ms=tick_ts_ms,
        )
    )

    assert state.open_time == open_time
    assert state.close_time == close_time
