from __future__ import annotations

import time
from typing import List, Optional

from config.config import Config
from core.validation.validator import ContractError, SchemaValidator
from observability.metrics import Metrics
from runtime.backfill import run_backfill
from runtime.final.publisher_final import publish_final_1m, publish_final_htf
from runtime.history_provider import HistoryProvider
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager
from store.derived_builder import build_htf_final
from store.sqlite_store import SQLiteStore


def run_final_ingest(
    config: Config,
    store: SQLiteStore,
    provider: HistoryProvider,
    status: StatusManager,
    metrics: Optional[Metrics],
    publisher: RedisPublisher,
    validator: SchemaValidator,
    symbol: str,
    start_ms: int,
    end_ms: int,
    tfs: Optional[List[str]] = None,
) -> None:
    """Оркестратор final ingest (1m) з backfill у store."""
    run_backfill(
        config=config,
        store=store,
        provider=provider,
        status=status,
        metrics=metrics,
        symbol=symbol,
        start_ms=start_ms,
        end_ms=end_ms,
        publish_callback=None,
        rebuild_timeframes=None,
        rebuild_callback=None,
    )
    store.trim_retention_days(symbol, config.retention_days)
    _publish_1m_from_store(
        config=config,
        store=store,
        publisher=publisher,
        validator=validator,
        symbol=symbol,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    _rebuild_and_publish_htf(
        config=config,
        store=store,
        publisher=publisher,
        validator=validator,
        status=status,
        metrics=metrics,
        symbol=symbol,
        start_ms=start_ms,
        end_ms=end_ms,
        tfs=tfs or ["5m", "15m", "1h", "4h", "1d"],
    )


def _publish_1m_from_store(
    config: Config,
    store: SQLiteStore,
    publisher: RedisPublisher,
    validator: SchemaValidator,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> None:
    limit = int(config.max_bars_per_message)
    t = start_ms
    while t <= end_ms:
        rows = store.query_1m_range(symbol, t, end_ms, limit)
        if not rows:
            break
        payload_bars = [
            {
                "open_time": r["open_time_ms"],
                "close_time": r["close_time_ms"],
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"],
                "volume": r["volume"],
                "complete": True,
                "synthetic": False,
                "source": "history",
                "event_ts": r["event_ts_ms"],
            }
            for r in rows
        ]
        publish_final_1m(publisher, validator, symbol, payload_bars)
        last_open = int(rows[-1]["open_time_ms"])
        t = last_open + 60_000


def _rebuild_and_publish_htf(
    config: Config,
    store: SQLiteStore,
    publisher: RedisPublisher,
    validator: SchemaValidator,
    status: StatusManager,
    metrics: Optional[Metrics],
    symbol: str,
    start_ms: int,
    end_ms: int,
    tfs: List[str],
) -> None:
    limit = int((end_ms - start_ms) / 60_000) + 1
    rows_1m = store.query_1m_range(symbol, start_ms, end_ms, limit)
    if not rows_1m:
        return
    for tf in tfs:
        try:
            htf_rows, _skipped = build_htf_final(
                symbol=symbol,
                tf=tf,
                bars_1m=rows_1m,
                trading_day_boundary_utc=config.trading_day_boundary_utc,
            )
        except ContractError as exc:
            status.append_error(
                code="derived_build_error",
                severity="error",
                message=str(exc),
                context={"symbol": symbol, "tf": tf},
            )
            status.mark_degraded("derived_build_error")
            raise
        ingest_ts_ms = int(time.time() * 1000)
        for bar in htf_rows:
            bar["ingest_ts_ms"] = ingest_ts_ms
        upserted = store.upsert_htf_final(symbol, tf, htf_rows)
        if metrics is not None:
            metrics.htf_final_bars_upserted_total.labels(tf=tf).inc(upserted)
        payload_bars = [
            {
                "open_time": b["open_time_ms"],
                "close_time": b["close_time_ms"],
                "open": b["open"],
                "high": b["high"],
                "low": b["low"],
                "close": b["close"],
                "volume": b["volume"],
                "complete": True,
                "synthetic": False,
                "source": "history_agg",
                "event_ts": b["event_ts_ms"],
            }
            for b in htf_rows
        ]
        publish_final_htf(publisher, validator, symbol, tf, payload_bars)
