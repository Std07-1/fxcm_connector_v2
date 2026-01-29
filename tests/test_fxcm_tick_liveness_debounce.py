from __future__ import annotations

from runtime.fxcm.tick_liveness import FxcmTickLiveness


def test_fxcm_tick_liveness_debounce() -> None:
    liveness = FxcmTickLiveness(stale_s=10, cooldown_s=20)
    now_ms = 1_000_000
    last_tick_ts_ms = now_ms - 11_000

    first = liveness.check(
        now_ms=now_ms,
        is_market_open=True,
        last_tick_ts_ms=last_tick_ts_ms,
        last_reconnect_req_ms=0,
    )
    assert first.action == "request_reconnect"

    second = liveness.check(
        now_ms=now_ms + 1000,
        is_market_open=True,
        last_tick_ts_ms=last_tick_ts_ms,
        last_reconnect_req_ms=now_ms,
    )
    assert second.action is None
