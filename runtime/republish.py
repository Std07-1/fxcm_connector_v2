from __future__ import annotations

import time
from typing import Any, Iterable, List, Optional

from config.config import Config
from core.time.buckets import TF_TO_MS
from core.validation.validator import ContractError, SchemaValidator
from observability.metrics import Metrics
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager
from store.file_cache import FileCache


def republish_tail(
    config: Config,
    file_cache: FileCache,
    redis_client: Optional[Any],
    publisher: RedisPublisher,
    validator: SchemaValidator,
    status: StatusManager,
    metrics: Optional[Metrics],
    symbol: str,
    timeframes: Iterable[str],
    window_hours: int,
    force: bool,
    req_id: str,
) -> None:
    now_ms = int(time.time() * 1000)
    ttl_s = int(config.republish_watermark_ttl_s)
    published_batches = 0
    skipped_any = False
    watermark_used = False

    if redis_client is None:
        status.append_error(
            code="republish_error",
            severity="error",
            message="Redis недоступний для watermark",
            context={"symbol": symbol},
        )
        status.mark_degraded("republish_watermark_unavailable")
        raise ValueError("Redis недоступний для watermark")

    for tf in timeframes:
        final_source = _ensure_final_source_allowed(file_cache=file_cache, symbol=symbol, tf=tf, status=status)
        key = f"{config.ns}:internal:republish_watermark:{symbol}:{tf}:{window_hours}"
        mark_val = redis_client.get(key)
        if mark_val is not None and not force:
            skipped_any = True
            watermark_used = True
            if metrics is not None:
                metrics.republish_skipped_total.labels(tf=tf).inc()
            continue

        bars = _load_tail(file_cache, symbol, tf, window_hours, final_source)
        if bars:
            published_batches += _publish_bars(
                config=config,
                publisher=publisher,
                validator=validator,
                symbol=symbol,
                tf=tf,
                bars=bars,
            )
        redis_client.setex(key, ttl_s, str(now_ms))
        watermark_used = True
        if metrics is not None:
            metrics.republish_runs_total.labels(tf=tf).inc()
            if force:
                metrics.republish_forced_total.labels(tf=tf).inc()

    state = "ok"
    if skipped_any and published_batches == 0 and watermark_used:
        state = "skipped"
    status.record_republish(
        req_id=req_id,
        skipped_by_watermark=skipped_any,
        forced=force,
        published_batches=published_batches,
        state=state,
    )


def _load_tail(file_cache: FileCache, symbol: str, tf: str, window_hours: int, source: str) -> List[dict]:
    size = TF_TO_MS.get(tf)
    if size is None:
        return []
    limit = int((window_hours * 60 * 60 * 1000) / size)
    rows = file_cache.query(symbol=symbol, tf=tf, limit=limit)
    return [
        {
            "open_time": int(r["open_time_ms"]),
            "close_time": int(r["close_time_ms"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r["volume"]),
            "complete": True,
            "synthetic": False,
            "source": source,
            "event_ts": int(r["close_time_ms"]),
        }
        for r in rows
    ]


def _publish_bars(
    config: Config,
    publisher: RedisPublisher,
    validator: SchemaValidator,
    symbol: str,
    tf: str,
    bars: List[dict],
) -> int:
    if not bars:
        return 0
    max_bars = config.max_bars_per_message
    batches = 0
    for i in range(0, len(bars), max_bars):
        chunk = bars[i : i + max_bars]
        try:
            if tf == "1m":
                publisher.publish_ohlcv_final_1m(
                    symbol=symbol,
                    bars=chunk,
                    validator=validator,
                )
            else:
                publisher.publish_ohlcv_final_htf(
                    symbol=symbol,
                    tf=tf,
                    bars=chunk,
                    validator=validator,
                )
        except ContractError as exc:
            raise ContractError(f"republish: {exc}")
        batches += 1
    return batches


def _ensure_final_source_allowed(file_cache: FileCache, symbol: str, tf: str, status: StatusManager) -> str:
    _rows, meta = file_cache.load(symbol, tf)
    last_write_source = str(meta.get("last_write_source", ""))
    if last_write_source in {"stream", "stream_close", "", "none"}:
        status.append_error(
            code="republish_source_invalid",
            severity="error",
            message="republish_tail заборонено: cache має stream/stream_close як last_write_source",
            context={"symbol": symbol, "tf": tf, "last_write_source": last_write_source},
        )
        status.mark_degraded("republish_source_invalid")
        raise ContractError("republish_source_invalid")
    if last_write_source not in {"history", "history_agg"}:
        status.append_error(
            code="republish_source_invalid",
            severity="error",
            message="republish_tail заборонено: last_write_source не з FINAL_SOURCES",
            context={"symbol": symbol, "tf": tf, "last_write_source": last_write_source},
        )
        status.mark_degraded("republish_source_invalid")
        raise ContractError("republish_source_invalid")
    if tf == "1m" and last_write_source != "history":
        status.append_error(
            code="republish_source_invalid",
            severity="error",
            message="republish_tail заборонено: 1m має history",
            context={"symbol": symbol, "tf": tf, "last_write_source": last_write_source},
        )
        status.mark_degraded("republish_source_invalid")
        raise ContractError("republish_source_invalid")
    if tf != "1m" and last_write_source != "history_agg":
        status.append_error(
            code="republish_source_invalid",
            severity="error",
            message="republish_tail заборонено: HTF має history_agg",
            context={"symbol": symbol, "tf": tf, "last_write_source": last_write_source},
        )
        status.mark_degraded("republish_source_invalid")
        raise ContractError("republish_source_invalid")
    return last_write_source
