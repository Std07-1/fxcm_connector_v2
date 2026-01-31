from __future__ import annotations

from typing import Any, Dict, List, Optional

from config.config import Config
from runtime.fxcm_forexconnect import FxcmForexConnectStream


class _FakeCalendar:
    def __init__(self, values: List[int]) -> None:
        self._values = list(values)
        self._index = 0

    def next_open_ms(self, now_ms: int, symbol: Optional[str] = None) -> int:
        if not self._values:
            return now_ms
        value = self._values[min(self._index, len(self._values) - 1)]
        self._index += 1
        return int(value)

    def is_open(self, now_ms: int, symbol: Optional[str] = None) -> bool:
        return False


class _DummyStatus:
    def __init__(self, calendar: _FakeCalendar) -> None:
        self.calendar = calendar
        self.errors: List[Dict[str, Any]] = []
        self.degraded: List[str] = []

    def append_error(
        self,
        code: str,
        severity: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry: Dict[str, Any] = {"code": code, "severity": severity, "message": message}
        if context:
            entry["context"] = context
        self.errors.append(entry)

    def mark_degraded(self, code: str) -> None:
        self.degraded.append(code)


def test_fxcm_calendar_next_open_ms_monotonic() -> None:
    calendar = _FakeCalendar([2_000, 3_000, 4_000])
    status = _DummyStatus(calendar)
    # Для проходження type-check передаємо fake-статус як Any.
    status_any: Any = status
    stream = FxcmForexConnectStream(config=Config(), status=status_any, on_tick=lambda *_: None)

    now_values = [1_000, 1_500, 2_500]
    results = [stream._calendar_next_open_ms(now_ms) for now_ms in now_values]

    assert results[0] < results[1] < results[2]
    assert all(result > now_ms for result, now_ms in zip(results, now_values))
    assert not status.errors
    assert not status.degraded


def test_fxcm_calendar_next_open_ms_invalid_is_degraded_backoff() -> None:
    calendar = _FakeCalendar([1_000])
    status = _DummyStatus(calendar)
    # Для проходження type-check передаємо fake-статус як Any.
    status_any: Any = status
    stream = FxcmForexConnectStream(config=Config(), status=status_any, on_tick=lambda *_: None)

    now_ms = 2_000
    next_open_ms = stream._calendar_next_open_ms(now_ms)

    assert next_open_ms == now_ms + 60_000
    assert any(err.get("code") == "fxcm_calendar_next_open_invalid" for err in status.errors)
    assert "fxcm_calendar_next_open_invalid" in status.degraded
