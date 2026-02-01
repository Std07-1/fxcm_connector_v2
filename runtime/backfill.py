from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional

from config.config import Config
from core.time.buckets import bucket_close_ms
from observability.metrics import Metrics
from runtime.fxcm.history_provider import FxcmForexConnectHistoryAdapter, FxcmHistoryProvider
from runtime.history_provider import HistoryProvider, guard_history_ready
from runtime.status import StatusManager
from store.file_cache import FileCache


def _resolve_history_end_ms(now_ms: int, status: StatusManager) -> int:
    safety_lag_ms = 2 * 60_000
    safe_now = max(0, int(now_ms) - int(safety_lag_ms))
    calendar = status.calendar
    if calendar is None or calendar.health_error():
        return bucket_close_ms(safe_now, "1m")
    if calendar.is_open(now_ms):
        return bucket_close_ms(safe_now, "1m")
    last_close = calendar.last_trading_close_ms(now_ms)
    return bucket_close_ms(int(last_close), "1m")


def run_backfill(
    config: Config,
    file_cache: FileCache,
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
    log = logging.getLogger("backfill")
    safe_end_ms = _resolve_history_end_ms(int(time.time() * 1000), status)
    end_ms = min(int(end_ms), int(safe_end_ms))
    end_ms = end_ms - (end_ms % 60_000) - 1
    if end_ms < start_ms:
        raise ValueError("end_ms має бути >= start_ms після календарного clamp")
    chunk_ms = config.history_chunk_minutes * 60 * 1000
    limit = config.history_chunk_limit

    t = start_ms
    if isinstance(provider, FxcmHistoryProvider) and isinstance(provider.adapter, FxcmForexConnectHistoryAdapter):
        log.info("FXCM login component=history reason=backfill symbol=%s", symbol)
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
            bar["complete"] = True
        file_cache.append_complete_bars(symbol=symbol, tf="1m", bars=bars, source="history")
        if metrics is not None:
            metrics.store_upserts_total.inc(len(bars))
        rows, _meta = file_cache.load(symbol, "1m")
        if rows:
            first_open = int(rows[0]["open_time_ms"])
            last_close = int(rows[-1]["close_time_ms"])
            bars_total = len(rows)
            coverage_days = int(max(0, last_close - first_open + 1) / (24 * 60 * 60 * 1000))
            status.record_final_1m_coverage(
                first_open_ms=first_open,
                last_close_ms=last_close,
                bars=int(bars_total),
                coverage_days=int(coverage_days),
                retention_target_days=int(config.retention_target_days),
            )
        if publish_callback is not None:
            publish_callback(symbol)
        t = end_chunk + 60_000
    span_days = max(1, int((end_ms - start_ms + 1) / (24 * 60 * 60 * 1000)))
    rows, _meta = file_cache.load(symbol, "1m")
    bars_total_est = len(rows)
    last_close_ms = int(rows[-1]["close_time_ms"]) if rows else 0
    status.record_final_publish(
        last_complete_bar_ms=last_close_ms,
        now_ms=int(time.time() * 1000),
        lookback_days=span_days,
        bars_total_est=bars_total_est,
    )
    if rebuild_callback is not None:
        tfs = rebuild_timeframes or ["15m", "1h", "4h", "1d"]
        rebuild_callback(symbol, start_ms, end_ms, tfs)
