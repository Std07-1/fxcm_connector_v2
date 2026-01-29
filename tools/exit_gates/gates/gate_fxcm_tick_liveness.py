from __future__ import annotations

from typing import Tuple

from runtime.fxcm.tick_liveness import FxcmTickLiveness


def run() -> Tuple[bool, str]:
    liveness = FxcmTickLiveness(stale_s=10, cooldown_s=20)
    now_ms = 1_000_000
    last_tick_ts_ms = now_ms - 11_000

    first = liveness.check(
        now_ms=now_ms,
        is_market_open=True,
        last_tick_ts_ms=last_tick_ts_ms,
        last_reconnect_req_ms=0,
    )
    if first.action != "request_reconnect":
        return False, f"FAIL: expected reconnect, got={first.action} reason={first.reason}"

    second = liveness.check(
        now_ms=now_ms + 1000,
        is_market_open=True,
        last_tick_ts_ms=last_tick_ts_ms,
        last_reconnect_req_ms=now_ms,
    )
    if second.action is not None:
        return False, f"FAIL: cooldown not enforced, got={second.action}"

    return True, "OK: liveness debounce працює (cooldown блокує повторні reconnect)"
