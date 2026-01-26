from __future__ import annotations

import time
from typing import Callable, List, Optional

from config.config import Config
from observability.metrics import Metrics
from runtime.history_provider import HistoryProvider, guard_history_ready
from runtime.status import StatusManager
from store.sqlite_store import SQLiteStore


def run_backfill(
    config: Config,
    store: SQLiteStore,
    provider: HistoryProvider,
    status: StatusManager,
    metrics: Optional[Metrics],
    symbol: str,
    start_ms: int,
    end_ms: int,
    publish_callback: Optional[Callable[[str], None]],
    rebuild_timeframes: Optional[List[str]] = None,
    rebuild_callback: Optional[Callable[[str, int, int, List[str]], None]] = None,
) -> None:
    end_ms = end_ms - (end_ms % 60_000) - 1
    chunk_ms = config.history_chunk_minutes * 60 * 1000
    limit = config.history_chunk_limit

    t = start_ms
    guard_history_ready(
        provider=provider,
        calendar=status.calendar,
        status=status,
        metrics=metrics,
        symbol=str(symbol),
        now_ms=int(time.time() * 1000),
        context="backfill",
    )
    while t <= end_ms:
        end_chunk = min(t + chunk_ms - 1, end_ms)
        if metrics is not None:
            metrics.backfill_requests_total.inc()
        bars = provider.fetch_1m_final(symbol, t, end_chunk, limit)
        for bar in bars:
            bar["ingest_ts_ms"] = int(time.time() * 1000)
        store.upsert_1m_final(symbol, bars)
        if metrics is not None:
            metrics.store_upserts_total.inc(len(bars))
        coverage = store.get_1m_coverage(symbol)
        status.record_final_1m_coverage(
            first_open_ms=coverage.get("first_open_ms"),
            last_close_ms=coverage.get("last_close_ms"),
            bars=int(coverage.get("bars", 0)),
            coverage_days=int(coverage.get("coverage_days", 0)),
            retention_target_days=int(config.retention_target_days),
        )
        if publish_callback is not None:
            publish_callback(symbol)
        t = end_chunk + 60_000
    span_days = max(1, int((end_ms - start_ms + 1) / (24 * 60 * 60 * 1000)))
    bars_total_est = store.count_1m_final(symbol)
    status.record_final_publish(
        last_complete_bar_ms=end_ms,
        now_ms=int(time.time() * 1000),
        lookback_days=span_days,
        bars_total_est=bars_total_est,
    )
    if rebuild_callback is not None:
        tfs = rebuild_timeframes or ["15m", "1h", "4h", "1d"]
        rebuild_callback(symbol, start_ms, end_ms, tfs)
