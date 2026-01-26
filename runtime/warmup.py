from __future__ import annotations

import time
from typing import Callable, List, Optional

from config.config import Config
from observability.metrics import Metrics
from runtime.history_provider import HistoryProvider, guard_history_ready
from runtime.status import StatusManager
from store.sqlite_store import SQLiteStore


def run_warmup(
    config: Config,
    store: SQLiteStore,
    provider: HistoryProvider,
    status: StatusManager,
    metrics: Optional[Metrics],
    symbols: List[str],
    lookback_days: int,
    publish_callback: Optional[Callable[[str], None]],
    rebuild_derived: bool = False,
    rebuild_timeframes: Optional[List[str]] = None,
    rebuild_callback: Optional[Callable[[str, int, int, List[str]], None]] = None,
) -> None:
    real_now_ms = int(time.time() * 1000)
    end_close_ms = real_now_ms - (real_now_ms % 60_000) - 1
    now_ms = end_close_ms
    start_ms = end_close_ms - lookback_days * 24 * 60 * 60 * 1000
    chunk_ms = config.history_chunk_minutes * 60 * 1000
    limit = config.history_chunk_limit

    for symbol in symbols:
        guard_history_ready(
            provider=provider,
            calendar=status.calendar,
            status=status,
            metrics=metrics,
            symbol=str(symbol),
            now_ms=real_now_ms,
            context="warmup",
        )
        t = start_ms
        while t <= now_ms:
            end_ms = min(t + chunk_ms - 1, now_ms)
            if metrics is not None:
                metrics.warmup_requests_total.inc()
            bars = provider.fetch_1m_final(symbol, t, end_ms, limit)
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
            t = end_ms + 60_000
        bars_total_est = store.count_1m_final(symbol)
        status.record_final_publish(
            last_complete_bar_ms=end_close_ms,
            now_ms=now_ms,
            lookback_days=lookback_days,
            bars_total_est=bars_total_est,
        )
        if rebuild_derived and rebuild_callback is not None:
            tfs = rebuild_timeframes or ["15m", "1h", "4h", "1d"]
            rebuild_callback(symbol, start_ms, now_ms, tfs)
