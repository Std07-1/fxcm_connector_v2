from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from observability.metrics import Metrics
from runtime.fxcm.adapter import FxcmAdapter
from runtime.fxcm.fsm import FxcmFsmDecision, FxcmSessionFsm
from runtime.fxcm.tick_liveness import FxcmTickLiveness
from runtime.status import StatusManager


@dataclass
class FxcmSessionManager:
    fsm: FxcmSessionFsm
    status: StatusManager
    adapter: FxcmAdapter
    liveness: FxcmTickLiveness
    metrics: Optional[Metrics] = None
    last_reconnect_req_ms: int = 0

    def on_connected(self, now_ms: int) -> None:
        self.fsm.on_connected(now_ms)
        self._sync_status()

    def on_offers_subscribed(self, now_ms: int) -> None:
        self.fsm.on_offers_subscribed(now_ms)
        self._sync_status()

    def on_tick(self, tick_ts_ms: int) -> None:
        self.fsm.on_tick(tick_ts_ms)
        self.status.record_fxcm_tick_total(tick_ts_ms)
        self._sync_status()

    def on_timer(self, now_ms: int) -> FxcmFsmDecision:
        is_market_open = self.adapter.is_market_open(now_ms)
        decision = self.fsm.on_timer(now_ms=now_ms, is_market_open=is_market_open)
        if not is_market_open:
            self.status.clear_degraded("fxcm_stale_no_ticks")
            self._sync_status()
            return FxcmFsmDecision(action=None)
        if decision.action == "resubscribe":
            self.status.record_fxcm_stale_event()
            self.status.record_fxcm_resubscribe()
            self.status.mark_degraded("fxcm_stale_no_ticks")
            self._sync_status()
        if decision.action == "reconnect":
            self.status.mark_degraded("fxcm_stale_no_ticks")
            liveness = self.liveness.check(
                now_ms=now_ms,
                is_market_open=is_market_open,
                last_tick_ts_ms=int(self.fsm.last_tick_ts_ms),
                last_reconnect_req_ms=int(self.last_reconnect_req_ms),
            )
            if liveness.action == "request_reconnect":
                self.last_reconnect_req_ms = int(now_ms)
                self.status.record_fxcm_stale_event()
                self.status.record_fxcm_reconnect()
                self._sync_status()
                return decision
            self._sync_status()
            return FxcmFsmDecision(action=None)
        return decision

    def on_resubscribe_result(self, success: bool) -> FxcmFsmDecision:
        decision = self.fsm.on_resubscribe_result(success)
        self._sync_status()
        return decision

    def record_publish_fail(self, reason: str) -> None:
        self.status.record_fxcm_publish_fail()
        self.status.append_error(
            code="fxcm_publish_fail",
            severity="error",
            message=reason,
        )
        self.status.mark_degraded("fxcm_publish_fail")
        self._sync_status()

    def record_contract_reject(self, reason: str) -> None:
        self.status.record_fxcm_contract_reject()
        self.status.append_error(
            code="fxcm_contract_reject",
            severity="error",
            message=reason,
        )
        self.status.mark_degraded("fxcm_contract_reject")
        self._sync_status()

    def _sync_status(self) -> None:
        self.status.update_fxcm_fsm(
            fsm_state=self.fsm.state.value,
            last_tick_ts_ms=self.fsm.last_tick_ts_ms,
            stale_seconds=self.fsm.stale_seconds,
            last_action=self.fsm.last_action,
        )
