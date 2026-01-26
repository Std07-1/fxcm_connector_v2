from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from typing_extensions import Protocol

from core.time.calendar import Calendar
from observability.metrics import Metrics
from runtime.status import StatusManager


class ProviderNotConfiguredError(RuntimeError):
    """Провайдер не налаштований (loud error)."""


class HistoryProvider(Protocol):
    """Контракт провайдера історії 1m final."""

    def fetch_1m_final(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, Any]]: ...

    def is_history_ready(self) -> Tuple[bool, str]: ...

    def should_backoff(self, now_ms: int) -> bool: ...

    def note_not_ready(self, now_ms: int, reason: str) -> int: ...


@dataclass
class HistoryFetchResult:
    bars: List[Dict[str, Any]]
    next_start_ms: int


class HistoryNotReadyError(RuntimeError):
    """History not ready (loud)."""


def guard_history_ready(
    provider: HistoryProvider,
    calendar: Calendar,
    status: StatusManager,
    metrics: Optional[Metrics],
    symbol: str,
    now_ms: int,
    context: str,
) -> None:
    ready, reason = provider.is_history_ready()
    backoff_active = provider.should_backoff(int(now_ms))
    if ready and not backoff_active:
        status.record_history_state(
            ready=True,
            not_ready_reason="",
            history_retry_after_ms=0,
            next_trading_open_ms=calendar.next_open_ms(int(now_ms), symbol=symbol),
            backoff_ms=0,
            backoff_active=False,
        )
        if metrics is not None:
            metrics.fxcm_history_backoff_active.set(0)
        return

    reason_val = reason or "history_not_ready"
    retry_after_ms = int(provider.note_not_ready(int(now_ms), reason_val))
    next_open_ms = calendar.next_open_ms(int(now_ms), symbol=symbol)
    backoff_ms = max(0, retry_after_ms - int(now_ms))
    status.record_history_state(
        ready=False,
        not_ready_reason=reason_val,
        history_retry_after_ms=retry_after_ms,
        next_trading_open_ms=next_open_ms,
        backoff_ms=backoff_ms,
        backoff_active=backoff_active or retry_after_ms > int(now_ms),
    )
    status.append_error(
        code="fxcm_history_not_ready",
        severity="error",
        message="FXCM history не готовий",
        context={
            "symbol": symbol,
            "context": context,
            "reason": reason_val,
            "retry_after_ms": retry_after_ms,
            "next_trading_open_ms": next_open_ms,
        },
    )
    status.mark_degraded("history_not_ready")
    if backoff_active or retry_after_ms > int(now_ms):
        status.mark_degraded("history_backoff_active")
    status.update_last_command_result(
        {
            "result": "error",
            "history_not_ready": True,
            "retry_in_ms": backoff_ms,
            "next_open_ms": next_open_ms,
        }
    )
    if metrics is not None:
        metrics.fxcm_history_not_ready_total.labels(reason=reason_val).inc()
        metrics.fxcm_history_backoff_active.set(1 if backoff_active or retry_after_ms > int(now_ms) else 0)
    raise HistoryNotReadyError("history not ready")
