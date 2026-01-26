from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from config.config import Config
from core.time.buckets import TF_TO_MS, get_bucket_close_ms, get_bucket_open_ms
from core.validation.validator import ContractError, SchemaValidator
from observability.metrics import Metrics
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager
from store.derived_builder import build_htf_final
from store.sqlite_store import SQLiteStore


@dataclass
class _Range:
    start_ms: int
    end_ms: int


@dataclass
class DerivedRebuildCoordinator:
    """Координатор rebuild HTF final з single-inflight та coalesce."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _inflight: set = field(default_factory=set)
    _pending: dict = field(default_factory=dict)

    def rebuild(
        self,
        config: Config,
        store: SQLiteStore,
        status: StatusManager,
        metrics: Optional[Metrics],
        publisher: RedisPublisher,
        validator: SchemaValidator,
        symbol: str,
        tfs: Iterable[str],
        start_ms: int,
        end_ms: int,
    ) -> None:
        for tf in tfs:
            self._run_tf(
                config=config,
                store=store,
                status=status,
                metrics=metrics,
                publisher=publisher,
                validator=validator,
                symbol=symbol,
                tf=tf,
                start_ms=start_ms,
                end_ms=end_ms,
            )

    def _run_tf(
        self,
        config: Config,
        store: SQLiteStore,
        status: StatusManager,
        metrics: Optional[Metrics],
        publisher: RedisPublisher,
        validator: SchemaValidator,
        symbol: str,
        tf: str,
        start_ms: int,
        end_ms: int,
    ) -> None:
        key = (symbol, tf)
        while True:
            with self._lock:
                if key in self._inflight:
                    self._pending[key] = _Range(start_ms=start_ms, end_ms=end_ms)
                    status.record_derived_rebuild(
                        state="queued",
                        start_ms=start_ms,
                        end_ms=end_ms,
                        tfs=[tf],
                        last_error=None,
                    )
                    return
                self._inflight.add(key)
            try:
                self._rebuild_tf(
                    config,
                    store,
                    status,
                    metrics,
                    publisher,
                    validator,
                    symbol,
                    tf,
                    start_ms,
                    end_ms,
                )
            finally:
                with self._lock:
                    self._inflight.discard(key)
                    pending = self._pending.pop(key, None)
                if pending is None:
                    break
                start_ms, end_ms = pending.start_ms, pending.end_ms

    def _rebuild_tf(
        self,
        config: Config,
        store: SQLiteStore,
        status: StatusManager,
        metrics: Optional[Metrics],
        publisher: RedisPublisher,
        validator: SchemaValidator,
        symbol: str,
        tf: str,
        start_ms: int,
        end_ms: int,
    ) -> None:
        if tf == "1m":
            raise ValueError("rebuild_derived не підтримує tf=1m")
        if tf not in TF_TO_MS:
            raise ValueError(f"Невідомий TF: {tf}")

        bucket_size = TF_TO_MS[tf]
        bucket_open_start = get_bucket_open_ms(tf, start_ms, config.trading_day_boundary_utc)
        if bucket_open_start != start_ms:
            aligned_start = bucket_open_start + bucket_size
        else:
            aligned_start = bucket_open_start
        bucket_open_end = get_bucket_open_ms(tf, end_ms, config.trading_day_boundary_utc)
        aligned_end_close = get_bucket_close_ms(tf, bucket_open_end, config.trading_day_boundary_utc)
        if aligned_start > aligned_end_close:
            status.record_derived_rebuild(
                state="empty",
                start_ms=aligned_start,
                end_ms=aligned_end_close,
                tfs=[tf],
                last_error=None,
            )
            return
        minutes = int((aligned_end_close - aligned_start) / TF_TO_MS["1m"]) + 1

        if metrics is not None:
            metrics.derived_rebuild_runs_total.labels(tf=tf).inc()

        rows_1m = store.query_1m_range(symbol, aligned_start, aligned_end_close, minutes)
        if not rows_1m:
            status.record_derived_rebuild(
                state="empty",
                start_ms=aligned_start,
                end_ms=aligned_end_close,
                tfs=[tf],
                last_error=None,
            )
            return

        try:
            htf_bars, skipped = build_htf_final(
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
            status.record_derived_rebuild(
                state="error",
                start_ms=aligned_start,
                end_ms=aligned_end_close,
                tfs=[tf],
                last_error=str(exc),
            )
            if metrics is not None:
                metrics.derived_rebuild_errors_total.labels(tf=tf, code="build").inc()
            return

        if skipped > 0:
            status.append_error(
                code="derived_incomplete_bucket",
                severity="error",
                message="Пропущено неповні HTF bucket",
                context={"symbol": symbol, "tf": tf, "skipped": skipped},
            )
            status.mark_degraded("derived_incomplete_bucket")
            status.record_derived_rebuild(
                state="partial",
                start_ms=aligned_start,
                end_ms=aligned_end_close,
                tfs=[tf],
                last_error="incomplete_bucket",
            )
            if metrics is not None:
                metrics.derived_rebuild_errors_total.labels(tf=tf, code="incomplete_bucket").inc()

        ingest_ts_ms = int(time.time() * 1000)
        for bar in htf_bars:
            bar["ingest_ts_ms"] = ingest_ts_ms

        try:
            upserted = store.upsert_htf_final(symbol, tf, htf_bars)
        except ContractError as exc:
            status.append_error(
                code="no_mix_conflict",
                severity="error",
                message=str(exc),
                context={"symbol": symbol, "tf": tf},
            )
            status.record_no_mix_conflict(symbol=symbol, tf=tf, message=str(exc))
            status.mark_degraded("no_mix")
            status.record_derived_rebuild(
                state="error",
                start_ms=aligned_start,
                end_ms=aligned_end_close,
                tfs=[tf],
                last_error=str(exc),
            )
            if metrics is not None:
                metrics.no_mix_conflicts_total.labels(tf=tf).inc()
                metrics.derived_rebuild_errors_total.labels(tf=tf, code="no_mix").inc()
            return

        if metrics is not None:
            metrics.htf_final_bars_upserted_total.labels(tf=tf).inc(upserted)

        try:
            _publish_htf_bars(
                config=config,
                publisher=publisher,
                validator=validator,
                symbol=symbol,
                tf=tf,
                bars=htf_bars,
            )
        except ContractError as exc:
            status.append_error(
                code="derived_publish_error",
                severity="error",
                message=str(exc),
                context={"symbol": symbol, "tf": tf},
            )
            status.mark_degraded("derived_publish_error")
            status.record_derived_rebuild(
                state="error",
                start_ms=aligned_start,
                end_ms=aligned_end_close,
                tfs=[tf],
                last_error=str(exc),
            )
            if metrics is not None:
                metrics.derived_rebuild_errors_total.labels(tf=tf, code="publish").inc()
            return

        last_close_ms = int(htf_bars[-1]["close_time_ms"])
        lookback_days = max(1, int((aligned_end_close - aligned_start + 1) / TF_TO_MS["1d"]))
        status.record_final_publish(
            last_complete_bar_ms=last_close_ms,
            now_ms=int(time.time() * 1000),
            lookback_days=lookback_days,
            tf=tf,
        )
        if skipped == 0:
            status.record_derived_rebuild(
                state="ok",
                start_ms=aligned_start,
                end_ms=aligned_end_close,
                tfs=[tf],
                last_error=None,
            )


def _publish_htf_bars(
    config: Config,
    publisher: RedisPublisher,
    validator: SchemaValidator,
    symbol: str,
    tf: str,
    bars: List[dict],
) -> None:
    if not bars:
        return
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
        for b in bars
    ]
    publisher.publish_ohlcv_final_htf(
        symbol=symbol,
        tf=tf,
        bars=payload_bars,
        validator=validator,
    )
