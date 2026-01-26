from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from config.config import Config
from core.time.calendar import Calendar
from observability.metrics import Metrics
from runtime.fxcm.history_budget import HistoryBudget, build_history_budget
from runtime.fxcm.history_provider import FxcmHistoryProvider
from runtime.history_provider import HistoryProvider, guard_history_ready
from runtime.status import StatusManager
from store.sqlite_store import SQLiteStore


@dataclass
class RepairSummary:
    windows_repaired: int
    bars_ingested: int


def repair_missing_1m(
    config: Config,
    store: SQLiteStore,
    provider: HistoryProvider,
    calendar: Calendar,
    status: StatusManager,
    metrics: Optional[Metrics],
    symbol: str,
    ranges: List[Tuple[int, int]],
    max_gap_minutes: int,
    history_budget: Optional[HistoryBudget] = None,
) -> RepairSummary:
    total_missing = 0
    total_chunks = 0
    now_ms = int(time.time() * 1000)
    guard_history_ready(
        provider=provider,
        calendar=calendar,
        status=status,
        metrics=metrics,
        symbol=str(symbol),
        now_ms=now_ms,
        context="repair",
    )
    for start_ms, end_ms in ranges:
        span_ms = end_ms - start_ms + 1
        if span_ms > config.tail_guard_repair_max_window_ms:
            _raise_repair_budget(
                status,
                code="repair_budget_exceeded",
                message="Діапазон repair перевищує budget",
                context={
                    "symbol": symbol,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "span_ms": span_ms,
                    "max_window_ms": config.tail_guard_repair_max_window_ms,
                },
            )
        span_minutes = int(span_ms / 60_000)
        total_missing += span_minutes
        chunks = max(1, int((span_minutes + config.history_chunk_minutes - 1) / config.history_chunk_minutes))
        total_chunks += chunks
    if total_missing > config.tail_guard_repair_max_missing_bars:
        _raise_repair_budget(
            status,
            code="repair_budget_exceeded",
            message="Кількість missing барів перевищує budget",
            context={
                "symbol": symbol,
                "missing_bars": total_missing,
                "max_missing_bars": config.tail_guard_repair_max_missing_bars,
            },
        )
    if total_chunks > config.tail_guard_repair_max_history_chunks:
        _raise_repair_budget(
            status,
            code="repair_budget_exceeded",
            message="Кількість history чанків перевищує budget",
            context={
                "symbol": symbol,
                "chunks": total_chunks,
                "max_chunks": config.tail_guard_repair_max_history_chunks,
            },
        )
    windows_repaired = 0
    bars_ingested = 0
    budget = history_budget or build_history_budget(config.max_requests_per_minute)
    use_budget_wrapper = True
    if isinstance(provider, FxcmHistoryProvider):
        if provider.budget is None:
            provider.budget = budget
        use_budget_wrapper = False
    for start_ms, end_ms in ranges:
        span_minutes = int((end_ms - start_ms + 1) / 60_000)
        if span_minutes > max_gap_minutes:
            status.append_error(
                code="repair_range_too_large",
                severity="error",
                message="Діапазон repair перевищує ліміт",
                context={
                    "symbol": symbol,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "span_minutes": span_minutes,
                    "max_gap_minutes": max_gap_minutes,
                },
            )
            status.mark_degraded("repair_range_too_large")
            raise ValueError("repair перевищує ліміт для одного діапазону")

        if use_budget_wrapper:
            waited = budget.acquire(symbol)
            _ = waited
        try:
            bars = provider.fetch_1m_final(symbol, start_ms, end_ms, limit=span_minutes + 5)
        finally:
            if use_budget_wrapper:
                budget.release(symbol)
        now_ms = int(time.time() * 1000)
        for bar in bars:
            bar["ingest_ts_ms"] = now_ms
        upserted = store.upsert_1m_final(symbol, bars)
        if upserted > 0:
            windows_repaired += 1
        bars_ingested += int(upserted)
        if metrics is not None:
            metrics.store_upserts_total.inc(len(bars))

    return RepairSummary(windows_repaired=windows_repaired, bars_ingested=bars_ingested)


def _raise_repair_budget(status: StatusManager, code: str, message: str, context: dict) -> None:
    status.append_error(code=code, severity="error", message=message, context=context)
    status.mark_degraded(code)
    raise ValueError(message)
