from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Set


@dataclass
class HistoryBudget:
    """Token bucket + global/per-symbol inflight для history (1m)."""

    capacity: int
    refill_per_sec: float
    tokens: float = 0.0
    last_refill: float = field(default_factory=time.time)
    _global_inflight: bool = False
    _inflight: Set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cond: threading.Condition = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._cond = threading.Condition(self._lock)

    def acquire(self, symbol: str) -> bool:
        waited = False
        with self._cond:
            while True:
                if self._global_inflight:
                    waited = True
                    self._cond.wait(timeout=0.05)
                    continue
                if symbol in self._inflight:
                    waited = True
                    self._cond.wait(timeout=0.05)
                    continue
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    self._global_inflight = True
                    self._inflight.add(symbol)
                    return waited
                waited = True
                sleep_s = 0.1
                if self.refill_per_sec > 0:
                    sleep_s = max(0.01, (1.0 - self.tokens) / self.refill_per_sec)
                self._cond.wait(timeout=sleep_s)

    def release(self, symbol: str) -> None:
        with self._cond:
            self._inflight.discard(symbol)
            self._global_inflight = False
            self._cond.notify_all()

    def _refill(self) -> None:
        now = time.time()
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
        self.last_refill = now


def build_history_budget(max_requests_per_minute: int) -> HistoryBudget:
    capacity = max(1, int(max_requests_per_minute))
    refill = float(max_requests_per_minute) / 60.0
    return HistoryBudget(capacity=capacity, refill_per_sec=refill, tokens=capacity)
