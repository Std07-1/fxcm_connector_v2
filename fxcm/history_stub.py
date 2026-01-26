from __future__ import annotations

import math
from typing import Any, Dict, List


def generate_1m_history(symbol: str, start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
    """Генерує детерміновані 1m final бари для stub-історії (P3)."""

    bars: List[Dict[str, Any]] = []
    step = 60_000
    t = start_ms - (start_ms % step)
    while t <= end_ms:
        base = 2000.0 + math.sin(t / 3_600_000) * 0.5
        open_p = base
        high = base + 0.2
        low = base - 0.2
        close_p = base + 0.05
        bar = {
            "symbol": symbol,
            "open_time_ms": t,
            "close_time_ms": t + step - 1,
            "open": open_p,
            "high": high,
            "low": low,
            "close": close_p,
            "volume": 1.0,
            "complete": 1,
            "synthetic": 0,
            "source": "history",
            "event_ts_ms": t + step - 1,
        }
        bars.append(bar)
        t += step
    return bars
