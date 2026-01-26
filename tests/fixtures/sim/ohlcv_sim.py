from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config.config import Config


@dataclass
class OhlcvSimulator:
    """Dev-only генератор tick для preview OHLCV."""

    config: Config
    last_emit_ms: int = 0
    counter: int = 0

    def maybe_tick(self, now_ms: int) -> Optional[float]:
        if not self.config.ohlcv_sim_enabled:
            return None
        if now_ms - self.last_emit_ms < self.config.tick_sim_interval_ms:
            return None
        self.last_emit_ms = now_ms
        self.counter += 1
        bid = self.config.tick_sim_bid + (self.counter % 10) * 0.01
        ask = self.config.tick_sim_ask + (self.counter % 10) * 0.01
        return (bid + ask) / 2.0
