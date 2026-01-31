from __future__ import annotations

from datetime import datetime, timezone

from ui_lite.server import _compute_preview_stale_state


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_ui_lite_stale_grace_15m() -> None:
    now_ms = _ms(datetime(2026, 1, 30, 21, 45, 3, tzinfo=timezone.utc))
    last_open_ms = _ms(datetime(2026, 1, 30, 21, 30, 0, tzinfo=timezone.utc))
    last_open_by_tf = {"15m": last_open_ms}

    stale_tf, stale_delay_bars, expected_open_ms, last_open = _compute_preview_stale_state(
        now_ms=now_ms,
        last_open_by_tf=last_open_by_tf,
        calendar=None,
        market_open=True,
    )

    assert stale_tf == "15m"
    assert stale_delay_bars == 0
    assert expected_open_ms > 0
    assert last_open == last_open_ms
