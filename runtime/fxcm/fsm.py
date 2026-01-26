from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FxcmFsmState(str, Enum):
    CONNECTING = "connecting"
    SUBSCRIBED_OFFERS = "subscribed_offers"
    STREAMING = "streaming"
    STALE_NO_TICKS = "stale_no_ticks"
    RESUBSCRIBE = "resubscribe"
    RECONNECT = "reconnect"


@dataclass
class FxcmFsmDecision:
    action: Optional[str]
    backoff_s: float = 0.0
    reason: Optional[str] = None


@dataclass
class FxcmSessionFsm:
    stale_s: int
    resubscribe_retries: int
    reconnect_backoff_s: float
    reconnect_backoff_cap_s: float = 60.0

    state: FxcmFsmState = FxcmFsmState.CONNECTING
    last_tick_ts_ms: int = 0
    last_ok_ts_ms: int = 0
    stale_seconds: int = 0
    last_action: str = ""
    resubscribe_attempts: int = 0
    reconnect_attempts: int = 0
    stale_events_total: int = 0
    resubscribe_total: int = 0
    reconnect_total: int = 0

    def on_connected(self, now_ms: int) -> None:
        self.state = FxcmFsmState.CONNECTING
        self.last_ok_ts_ms = int(now_ms)
        self.last_action = "connected"

    def on_offers_subscribed(self, now_ms: int) -> None:
        _ = now_ms
        self.state = FxcmFsmState.SUBSCRIBED_OFFERS
        self.last_action = "subscribed_offers"
        self.resubscribe_attempts = 0

    def on_tick(self, tick_ts_ms: int) -> None:
        self.last_tick_ts_ms = int(tick_ts_ms)
        self.stale_seconds = 0
        self.state = FxcmFsmState.STREAMING
        self.last_action = "tick"

    def on_error(self, code: str) -> None:
        self.last_action = code

    def on_timer(self, now_ms: int, is_market_open: bool) -> FxcmFsmDecision:
        if not is_market_open:
            self.stale_seconds = 0
            return FxcmFsmDecision(action=None)
        base_ts = self.last_tick_ts_ms or self.last_ok_ts_ms
        if base_ts <= 0:
            self.stale_seconds = 0
            return FxcmFsmDecision(action=None)
        delta_s = max(0, int((now_ms - base_ts) / 1000))
        self.stale_seconds = delta_s
        if delta_s <= self.stale_s:
            return FxcmFsmDecision(action=None)

        if self.state not in {FxcmFsmState.STALE_NO_TICKS, FxcmFsmState.RESUBSCRIBE, FxcmFsmState.RECONNECT}:
            self.stale_events_total += 1
        self.state = FxcmFsmState.STALE_NO_TICKS
        self.last_action = "stale_no_ticks"

        if self.resubscribe_attempts < self.resubscribe_retries:
            self.resubscribe_attempts += 1
            self.resubscribe_total += 1
            self.state = FxcmFsmState.RESUBSCRIBE
            self.last_action = "resubscribe"
            return FxcmFsmDecision(action="resubscribe", reason="stale_no_ticks")

        self.reconnect_attempts += 1
        self.reconnect_total += 1
        self.state = FxcmFsmState.RECONNECT
        self.last_action = "reconnect"
        backoff_s = min(self.reconnect_backoff_cap_s, self.reconnect_backoff_s * (2 ** (self.reconnect_attempts - 1)))
        return FxcmFsmDecision(action="reconnect", backoff_s=backoff_s, reason="stale_no_ticks")

    def on_resubscribe_result(self, success: bool) -> FxcmFsmDecision:
        if success:
            self.state = FxcmFsmState.SUBSCRIBED_OFFERS
            self.last_action = "resubscribe_ok"
            return FxcmFsmDecision(action=None)
        self.reconnect_attempts += 1
        self.reconnect_total += 1
        self.state = FxcmFsmState.RECONNECT
        self.last_action = "reconnect"
        backoff_s = min(self.reconnect_backoff_cap_s, self.reconnect_backoff_s * (2 ** (self.reconnect_attempts - 1)))
        return FxcmFsmDecision(action="reconnect", backoff_s=backoff_s, reason="resubscribe_failed")
