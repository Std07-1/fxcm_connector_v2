from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from runtime.fxcm.history_budget import build_history_budget
from runtime.fxcm.history_provider import FxcmHistoryAdapter, FxcmHistoryProvider


class DummyAdapter(FxcmHistoryAdapter):
    def __init__(self, sleep_s: float = 0.2) -> None:
        self._sleep_s = sleep_s

    def fetch_1m(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, Any]]:
        time.sleep(self._sleep_s)
        return []


class DummyStatus:
    def __init__(self) -> None:
        self.errors: List[Dict[str, Any]] = []

    def append_error_throttled(
        self,
        code: str,
        severity: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        throttle_key: Optional[str] = None,
        throttle_ms: int = 60_000,
        now_ms: Optional[int] = None,
        external_last_ts_by_key: Optional[Dict[str, int]] = None,
        external_lock: Optional[threading.Lock] = None,
    ) -> bool:
        _ = throttle_key, throttle_ms, now_ms, external_last_ts_by_key, external_lock
        self.errors.append(
            {
                "code": code,
                "severity": severity,
                "message": message,
                "context": context or {},
            }
        )
        return True


def test_history_single_inflight_wait_visible() -> None:
    status: Any = DummyStatus()
    adapter = DummyAdapter(sleep_s=0.2)
    budget = build_history_budget(1)
    provider = FxcmHistoryProvider(adapter=adapter, budget=budget, status=status, metrics=None)

    def _call() -> None:
        provider._fetch_chunk("XAUUSD", 0, 60_000, 10)

    t1 = threading.Thread(target=_call)
    t2 = threading.Thread(target=_call)
    t1.start()
    time.sleep(0.02)
    t2.start()
    t1.join()
    t2.join()

    assert any(err.get("code") == "history_inflight_wait" for err in status.errors)
