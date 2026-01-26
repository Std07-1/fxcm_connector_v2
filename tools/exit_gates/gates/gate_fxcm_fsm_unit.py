from __future__ import annotations

from typing import Tuple

from runtime.fxcm.fsm import FxcmSessionFsm


def run() -> Tuple[bool, str]:
    fsm = FxcmSessionFsm(stale_s=5, resubscribe_retries=1, reconnect_backoff_s=2.0)
    now_ms = 1_700_000_000_000
    fsm.on_connected(now_ms)
    if fsm.state.value != "connecting":
        return False, "FAIL: state після on_connected має бути connecting"
    fsm.on_offers_subscribed(now_ms)
    if fsm.state.value != "subscribed_offers":
        return False, "FAIL: state після on_offers_subscribed має бути subscribed_offers"

    decision = fsm.on_timer(now_ms + 6_000, is_market_open=True)
    if decision.action != "resubscribe":
        return False, "FAIL: очікується resubscribe на stale"
    decision = fsm.on_resubscribe_result(False)
    if decision.action != "reconnect":
        return False, "FAIL: очікується reconnect після resubscribe fail"

    fsm.on_offers_subscribed(now_ms)
    fsm.on_tick(now_ms + 1_000)
    if fsm.state.value != "streaming":
        return False, "FAIL: state після on_tick має бути streaming"

    return True, "OK: FSM переходи та backoff перевірено"
