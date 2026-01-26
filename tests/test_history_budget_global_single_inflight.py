from __future__ import annotations

import threading
import time

from runtime.fxcm.history_budget import HistoryBudget


def test_history_budget_global_single_inflight() -> None:
    budget = HistoryBudget(capacity=1, refill_per_sec=1.0, tokens=1.0)
    acquired_first = threading.Event()
    acquired_second = threading.Event()
    release_first = threading.Event()

    def worker_first() -> None:
        budget.acquire("EURUSD")
        acquired_first.set()
        release_first.wait(timeout=2.0)
        budget.release("EURUSD")

    def worker_second() -> None:
        acquired_first.wait(timeout=2.0)
        budget.acquire("XAUUSD")
        acquired_second.set()
        budget.release("XAUUSD")

    t1 = threading.Thread(target=worker_first)
    t2 = threading.Thread(target=worker_second)
    t1.start()
    t2.start()

    assert acquired_first.wait(timeout=1.0)
    time.sleep(0.1)
    assert not acquired_second.is_set()

    release_first.set()
    assert acquired_second.wait(timeout=1.0)

    t1.join(timeout=1.0)
    t2.join(timeout=1.0)
