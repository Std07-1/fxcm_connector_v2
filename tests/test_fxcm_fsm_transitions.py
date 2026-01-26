from __future__ import annotations

from runtime.fxcm.fsm import FxcmFsmState, FxcmSessionFsm


def test_fxcm_fsm_basic_transitions() -> None:
    fsm = FxcmSessionFsm(stale_s=5, resubscribe_retries=1, reconnect_backoff_s=2.0)
    now_ms = 1_700_000_000_000
    fsm.on_connected(now_ms)
    assert fsm.state == FxcmFsmState.CONNECTING

    fsm.on_offers_subscribed(now_ms)
    assert fsm.state == FxcmFsmState.SUBSCRIBED_OFFERS

    fsm.on_tick(now_ms + 1_000)
    assert fsm.state == FxcmFsmState.STREAMING
