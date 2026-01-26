from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.time.calendar import Calendar
from runtime.history_provider import HistoryProvider


@dataclass
class HistorySimProvider(HistoryProvider):
    """Dev-only детермінований генератор 1m final історії."""

    calendar: Optional[Calendar] = None
    history_retry_after_ms: int = 0

    def is_history_ready(self):
        return True, ""

    def should_backoff(self, now_ms: int) -> bool:
        return int(now_ms) < int(self.history_retry_after_ms)

    def note_not_ready(self, now_ms: int, reason: str) -> int:
        _ = reason
        if int(self.history_retry_after_ms) > int(now_ms):
            return int(self.history_retry_after_ms)
        self.history_retry_after_ms = int(now_ms) + 60_000
        return int(self.history_retry_after_ms)

    def fetch_1m_final(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, Any]]:
        bars: List[Dict[str, Any]] = []
        step = 60_000
        t = start_ms - (start_ms % step)
        while t <= end_ms and len(bars) < limit:
            if self.calendar is not None and not self.calendar.is_open(t, symbol=symbol):
                t += step
                continue
            base = 2000.0 + math.sin(t / 3_600_000) * 0.5
            o = base
            h = base + 0.2
            low = base - 0.2
            c = base + 0.05
            bar = {
                "symbol": symbol,
                "open_time_ms": t,
                "close_time_ms": t + step - 1,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 1.0,
                "complete": 1,
                "synthetic": 0,
                "source": "history",
                "event_ts_ms": t + step - 1,
            }
            bars.append(bar)
            t += step
        return bars
