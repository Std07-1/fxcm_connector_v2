from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.market.tick import Tick


@dataclass
class Preview1mState:
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "open_time": self.open_time,
            "close_time": self.close_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "tick_count": self.tick_count,
            "complete": False,
            "synthetic": False,
            "source": "stream",
        }


@dataclass
class Preview1mBuilder:
    current: Optional[Preview1mState] = None

    def on_tick(self, tick: Tick) -> Preview1mState:
        open_time = (tick.tick_ts_ms // 60_000) * 60_000
        close_time = open_time + 60_000 - 1
        if self.current is None or self.current.open_time != open_time:
            self.current = Preview1mState(
                open_time=open_time,
                close_time=close_time,
                open=tick.mid,
                high=tick.mid,
                low=tick.mid,
                close=tick.mid,
                volume=1.0,
                tick_count=1,
            )
        else:
            self.current.high = max(self.current.high, tick.mid)
            self.current.low = min(self.current.low, tick.mid)
            self.current.close = tick.mid
            self.current.volume += 1.0
            self.current.tick_count += 1
        return self.current
