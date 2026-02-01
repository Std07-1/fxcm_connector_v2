from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from typing_extensions import Protocol

from config.config import Config
from core.time.buckets import TF_TO_MS, get_bucket_close_ms, get_bucket_open_ms
from core.validation.validator import ContractError, SchemaValidator
from observability.metrics import Metrics
from runtime.history_provider import HistoryNotReadyError, HistoryProvider, guard_history_ready
from runtime.status import StatusManager
from store.file_cache import FileCache


class PublisherProtocol(Protocol):
    def publish_ohlcv_final_1m(self, symbol: str, bars: List[Dict[str, Any]], validator: SchemaValidator) -> None: ...

    def publish_ohlcv_final_htf(
        self,
        symbol: str,
        tf: str,
        bars: List[Dict[str, Any]],
        validator: SchemaValidator,
    ) -> None: ...


@dataclass
class ReconcileSummary:
    symbol: str
    bucket_open_ms: int
    bucket_close_ms: int
    lookback_minutes: int
    published_1m: int
    skipped_1m: int
    published_15m: int
    skipped_15m: int
    state: str


def reconcile_final_tail(
    config: Config,
    file_cache: FileCache,
    provider: HistoryProvider,
    publisher: PublisherProtocol,
    validator: SchemaValidator,
    status: StatusManager,
    metrics: Optional[Metrics],
    symbol: str,
    lookback_minutes: int,
    req_id: str,
    target_close_ms: Optional[int] = None,
) -> ReconcileSummary:
    if not config.reconcile_enable:
        raise ValueError("reconcile вимкнений у конфігу")
    lookback = int(lookback_minutes)
    if lookback < 15:
        raise ValueError("lookback_minutes має бути >= 15")

    now_ms = int(time.time() * 1000)
    if target_close_ms is None:
        current_open = get_bucket_open_ms("15m", now_ms, status.calendar)
        target_close = int(current_open) - 1
    else:
        target_close = int(target_close_ms)
    tf_ms = TF_TO_MS["15m"]
    bucket_open_ms = int(target_close - tf_ms + 1)
    bucket_close_ms = int(target_close)
    if bucket_open_ms % tf_ms != 0 or bucket_close_ms != bucket_open_ms + tf_ms - 1:
        raise ValueError("target_close_ms має бути вирівняний по 15m close")
    start_ms = int(bucket_close_ms - lookback * 60_000 + 1)

    published_1m = 0
    skipped_1m = 0
    published_15m = 0
    skipped_15m = 0
    state = "ok"
    error: Optional[Dict[str, Any]] = None

    try:
        guard_history_ready(
            provider=provider,
            calendar=status.calendar,
            status=status,
            metrics=metrics,
            symbol=str(symbol),
            now_ms=int(now_ms),
            context="reconcile",
        )
        limit = max(lookback + 5, 15)
        rows = provider.fetch_1m_final(symbol, start_ms, bucket_close_ms, limit)
        history_bars = _normalize_history_rows(rows, start_ms, bucket_close_ms)
        if not history_bars:
            raise ContractError("reconcile_history_empty")

        ingest_ts_ms = int(time.time() * 1000)
        for bar in history_bars:
            bar["ingest_ts_ms"] = ingest_ts_ms
            bar["complete"] = True
        file_cache.append_complete_bars(symbol=symbol, tf="1m", bars=history_bars, source="history")

        _rows_1m, meta_1m = file_cache.load(symbol, "1m")
        last_published_1m = int(meta_1m.get("last_published_open_time_ms", 0))
        history_bars_sorted = sorted(history_bars, key=lambda b: int(b["open_time_ms"]))
        publish_1m = [b for b in history_bars_sorted if int(b["open_time_ms"]) > last_published_1m]
        skipped_1m = max(0, len(history_bars_sorted) - len(publish_1m))
        if publish_1m:
            payload_1m = [_history_to_final_bar(b, source="history") for b in publish_1m]
            publisher.publish_ohlcv_final_1m(symbol=symbol, bars=payload_1m, validator=validator)
            published_1m = len(payload_1m)
            file_cache.mark_published(symbol, "1m", int(payload_1m[-1]["open_time"]))

        aggregated_15m, incomplete = _aggregate_15m(history_bars_sorted, status.calendar)
        target_bucket_open = int(bucket_open_ms)
        if target_bucket_open in incomplete:
            raise ContractError("reconcile_15m_incomplete")
        if not any(int(bar.get("open_time", 0)) == target_bucket_open for bar in aggregated_15m):
            raise ContractError("reconcile_15m_missing")

        cache_15m = [_final_to_cache_bar(b) for b in aggregated_15m]
        if cache_15m:
            file_cache.append_complete_bars(symbol=symbol, tf="15m", bars=cache_15m, source="history_agg")

        _rows_15m, meta_15m = file_cache.load(symbol, "15m")
        last_published_15m = int(meta_15m.get("last_published_open_time_ms", 0))
        publish_15m = [b for b in aggregated_15m if int(b["open_time"]) > last_published_15m]
        skipped_15m = max(0, len(aggregated_15m) - len(publish_15m))
        if publish_15m:
            publisher.publish_ohlcv_final_htf(symbol=symbol, tf="15m", bars=publish_15m, validator=validator)
            published_15m = len(publish_15m)
            file_cache.mark_published(symbol, "15m", int(publish_15m[-1]["open_time"]))
    except HistoryNotReadyError:
        state = "error"
        error = {
            "code": "reconcile_history_not_ready",
            "message": "FXCM history не готовий для reconcile",
            "ts": int(time.time() * 1000),
        }
        raise
    except Exception as exc:  # noqa: BLE001
        state = "error"
        error = {
            "code": "reconcile_error",
            "message": str(exc),
            "ts": int(time.time() * 1000),
        }
        raise
    finally:
        status.record_reconcile(
            req_id=req_id,
            bucket_open_ms=int(bucket_open_ms),
            bucket_close_ms=int(bucket_close_ms),
            lookback_minutes=int(lookback),
            published_1m=int(published_1m),
            skipped_1m=int(skipped_1m),
            published_15m=int(published_15m),
            skipped_15m=int(skipped_15m),
            state=state,
            error=error,
        )

    return ReconcileSummary(
        symbol=str(symbol),
        bucket_open_ms=int(bucket_open_ms),
        bucket_close_ms=int(bucket_close_ms),
        lookback_minutes=int(lookback),
        published_1m=int(published_1m),
        skipped_1m=int(skipped_1m),
        published_15m=int(published_15m),
        skipped_15m=int(skipped_15m),
        state=str(state),
    )


def _normalize_history_rows(
    rows: Iterable[Dict[str, Any]],
    start_ms: int,
    end_ms: int,
) -> List[Dict[str, Any]]:
    merged: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        open_ms = int(row.get("open_time_ms") or row.get("open_time") or 0)
        close_ms = int(row.get("close_time_ms") or row.get("close_time") or 0)
        if open_ms <= 0 or close_ms <= 0:
            continue
        if open_ms < start_ms or open_ms > end_ms:
            continue
        open_val = row.get("open")
        high_val = row.get("high")
        low_val = row.get("low")
        close_val = row.get("close")
        if open_val is None or high_val is None or low_val is None or close_val is None:
            continue
        merged[open_ms] = {
            "open_time_ms": open_ms,
            "close_time_ms": close_ms,
            "open": float(open_val),
            "high": float(high_val),
            "low": float(low_val),
            "close": float(close_val),
            "volume": float(row.get("volume", 0.0)),
            "tick_count": int(row.get("tick_count", 0)),
        }
    result = list(merged.values())
    result.sort(key=lambda b: int(b["open_time_ms"]))
    return result


def _history_to_final_bar(row: Dict[str, Any], source: str) -> Dict[str, Any]:
    open_ms = int(row["open_time_ms"])
    close_ms = int(row["close_time_ms"])
    return {
        "open_time": open_ms,
        "close_time": close_ms,
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row.get("volume", 0.0)),
        "complete": True,
        "synthetic": False,
        "source": source,
        "event_ts": close_ms,
    }


def _final_to_cache_bar(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "open_time_ms": int(row["open_time"]),
        "close_time_ms": int(row["close_time"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row.get("volume", 0.0)),
        "tick_count": int(row.get("tick_count", 0)),
        "complete": True,
    }


def _aggregate_15m(
    rows: List[Dict[str, Any]],
    calendar: Any,
) -> Tuple[List[Dict[str, Any]], List[int]]:
    bucketed: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        open_ms = int(row["open_time_ms"])
        bucket_open = int(get_bucket_open_ms("15m", open_ms, calendar))
        bucketed.setdefault(bucket_open, []).append(row)

    expected = int(TF_TO_MS["15m"] / TF_TO_MS["1m"])
    aggregated: List[Dict[str, Any]] = []
    incomplete: List[int] = []
    for bucket_open, items in sorted(bucketed.items()):
        items_sorted = sorted(items, key=lambda b: int(b["open_time_ms"]))
        if len(items_sorted) != expected:
            incomplete.append(int(bucket_open))
            continue
        ok = True
        for idx, bar in enumerate(items_sorted):
            expected_open = int(bucket_open + idx * TF_TO_MS["1m"])
            if int(bar["open_time_ms"]) != expected_open:
                ok = False
                break
        if not ok:
            incomplete.append(int(bucket_open))
            continue
        open_val = float(items_sorted[0]["open"])
        close_val = float(items_sorted[-1]["close"])
        high_val = max(float(b["high"]) for b in items_sorted)
        low_val = min(float(b["low"]) for b in items_sorted)
        volume_val = sum(float(b.get("volume", 0.0)) for b in items_sorted)
        tick_count_val = sum(int(b.get("tick_count", 0)) for b in items_sorted)
        close_ms = int(get_bucket_close_ms("15m", int(bucket_open), calendar))
        aggregated.append(
            {
                "open_time": int(bucket_open),
                "close_time": close_ms,
                "open": open_val,
                "high": high_val,
                "low": low_val,
                "close": close_val,
                "volume": float(volume_val),
                "tick_count": int(tick_count_val),
                "complete": True,
                "synthetic": False,
                "source": "history_agg",
                "event_ts": close_ms,
            }
        )
    return aggregated, incomplete
