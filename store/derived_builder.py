from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.time.buckets import TF_TO_MS, get_bucket_close_ms, get_bucket_open_ms
from core.validation.validator import ContractError
from store.bars_store import BarsStoreSQLite


@dataclass
class DerivedBucket:
    start_ms: int
    close_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    count: int
    last_open_time_ms: int


def _expected_count(tf: str) -> int:
    size = TF_TO_MS.get(tf)
    if size is None:
        raise ContractError(f"Невідомий TF для HTF агрегації: {tf}")
    return int(size / TF_TO_MS["1m"])


def build_htf_final(
    symbol: str,
    tf: str,
    bars_1m: Iterable[Dict[str, Any]],
    trading_day_boundary_utc: str = "22:00",
) -> Tuple[List[Dict[str, Any]], int]:
    """Детермінована агрегація 1m final → HTF final (з підрахунком пропущених bucket)."""
    if tf == "1m":
        raise ContractError("HTF агрегація не застосовується для 1m")
    expected = _expected_count(tf)
    results: List[Dict[str, Any]] = []
    bucket: Optional[DerivedBucket] = None
    for bar in bars_1m:
        open_time_ms = int(bar["open_time_ms"])
        close_time_ms = int(bar["close_time_ms"])
        bucket_start = get_bucket_open_ms(tf, open_time_ms, trading_day_boundary_utc)
        bucket_close = get_bucket_close_ms(tf, bucket_start, trading_day_boundary_utc)
        if bucket is None or bucket.start_ms != bucket_start:
            if bucket is not None:
                _finalize_bucket(symbol, tf, expected, bucket, results)
            bucket = DerivedBucket(
                start_ms=bucket_start,
                close_ms=bucket_close,
                open=float(bar["open"]),
                high=float(bar["high"]),
                low=float(bar["low"]),
                close=float(bar["close"]),
                volume=float(bar["volume"]),
                count=1,
                last_open_time_ms=open_time_ms,
            )
        else:
            if open_time_ms != bucket.last_open_time_ms + TF_TO_MS["1m"]:
                raise ContractError("Пропущений 1m бар у bucket HTF")
            bucket.high = max(bucket.high, float(bar["high"]))
            bucket.low = min(bucket.low, float(bar["low"]))
            bucket.close = float(bar["close"])
            bucket.volume += float(bar["volume"])
            bucket.count += 1
            bucket.last_open_time_ms = open_time_ms
        if close_time_ms > bucket.close_ms:
            raise ContractError("1m бар виходить за межі HTF bucket")
    if bucket is not None:
        _finalize_bucket(symbol, tf, expected, bucket, results)
    return results, 0


@dataclass
class DerivedBuilder:
    """Побудова HTF final з SSOT 1m final у SQLite."""

    bars_store: BarsStoreSQLite
    trading_day_boundary_utc: str

    def build_range(self, symbol: str, tf: str, start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
        if tf == "1m":
            raise ValueError("HTF агрегація не підтримує tf=1m")
        if tf not in TF_TO_MS:
            raise ValueError("Невідомий TF для агрегації: " + tf)
        if start_ms <= 0 or end_ms <= 0 or start_ms > end_ms:
            raise ValueError("Некоректний діапазон часу")
        limit = int((end_ms - start_ms) / TF_TO_MS["1m"]) + 1
        rows_1m = self.bars_store.query_range(symbol=symbol, start_ms=start_ms, end_ms=end_ms, limit=limit)
        if not rows_1m:
            return []
        htf_rows, _skipped = build_htf_final(
            symbol=symbol,
            tf=tf,
            bars_1m=rows_1m,
            trading_day_boundary_utc=self.trading_day_boundary_utc,
        )
        results: List[Dict[str, Any]] = []
        for row in htf_rows:
            results.append(
                {
                    "open_time": int(row["open_time_ms"]),
                    "close_time": int(row["close_time_ms"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "complete": True,
                    "synthetic": False,
                    "source": "history_agg",
                    "event_ts": int(row["event_ts_ms"]),
                }
            )
        return results


def _finalize_bucket(
    symbol: str,
    tf: str,
    expected: int,
    bucket: DerivedBucket,
    results: List[Dict[str, Any]],
) -> bool:
    if bucket.count != expected:
        raise ContractError("Неповний HTF bucket: пропущено 1m бар")
    if bucket.last_open_time_ms != bucket.start_ms + (expected - 1) * TF_TO_MS["1m"]:
        raise ContractError("Неповний HTF bucket: порушено послідовність 1m")
    if bucket.close_ms != bucket.start_ms + TF_TO_MS[tf] - 1:
        raise ContractError("close_time має дорівнювати bucket_end_ms - 1")
    results.append(
        {
            "symbol": symbol,
            "open_time_ms": bucket.start_ms,
            "close_time_ms": bucket.close_ms,
            "open": bucket.open,
            "high": bucket.high,
            "low": bucket.low,
            "close": bucket.close,
            "volume": bucket.volume,
            "complete": 1,
            "synthetic": 0,
            "source": "history_agg",
            "event_ts_ms": bucket.close_ms,
        }
    )
    return True
