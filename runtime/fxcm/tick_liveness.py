from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class FxcmTickLivenessDecision:
    action: Optional[str]
    reason: str
    next_allowed_reconnect_ts_ms: int


@dataclass
class FxcmTickLiveness:
    stale_s: int
    cooldown_s: int

    def check(
        self,
        now_ms: int,
        is_market_open: bool,
        last_tick_ts_ms: int,
        last_reconnect_req_ms: int,
    ) -> FxcmTickLivenessDecision:
        if not is_market_open:
            return FxcmTickLivenessDecision(
                action=None,
                reason="market_closed",
                next_allowed_reconnect_ts_ms=int(now_ms),
            )
        if last_tick_ts_ms <= 0:
            return FxcmTickLivenessDecision(
                action=None,
                reason="no_ticks_yet",
                next_allowed_reconnect_ts_ms=int(now_ms),
            )
        age_s = int(max(0, now_ms - last_tick_ts_ms) / 1000)
        if age_s <= int(self.stale_s):
            return FxcmTickLivenessDecision(
                action=None,
                reason="ok",
                next_allowed_reconnect_ts_ms=int(now_ms),
            )
        next_allowed = int(last_reconnect_req_ms) + int(self.cooldown_s) * 1000
        if last_reconnect_req_ms > 0 and now_ms < next_allowed:
            return FxcmTickLivenessDecision(
                action=None,
                reason="cooldown",
                next_allowed_reconnect_ts_ms=next_allowed,
            )
        return FxcmTickLivenessDecision(
            action="request_reconnect",
            reason="stale_no_ticks",
            next_allowed_reconnect_ts_ms=int(now_ms + int(self.cooldown_s) * 1000),
        )
