from __future__ import annotations

from runtime.fxcm.fsm import FxcmSessionFsm


def test_fxcm_stale_policy_resubscribe_then_reconnect() -> None:
    fsm = FxcmSessionFsm(stale_s=5, resubscribe_retries=1, reconnect_backoff_s=2.0)
    now_ms = 1_700_000_000_000
    fsm.on_connected(now_ms)
    fsm.on_offers_subscribed(now_ms)

    decision = fsm.on_timer(now_ms + 6_000, is_market_open=True)
    assert decision.action == "resubscribe"

    decision = fsm.on_resubscribe_result(False)
    assert decision.action == "reconnect"
    assert decision.backoff_s >= 2.0


def test_fxcm_stale_policy_market_closed_no_action() -> None:
    fsm = FxcmSessionFsm(stale_s=5, resubscribe_retries=1, reconnect_backoff_s=2.0)
    now_ms = 1_700_000_000_000
    fsm.on_connected(now_ms)
    fsm.on_offers_subscribed(now_ms)

    decision = fsm.on_timer(now_ms + 60_000, is_market_open=False)
    assert decision.action is None
    assert fsm.stale_seconds == 0
