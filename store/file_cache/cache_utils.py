from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple

from core.time.buckets import TF_TO_MS

CACHE_VERSION = 1
CACHE_COLUMNS = [
    "open_time_ms",
    "close_time_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "complete",
    "synthetic",
    "source",
    "event_ts_ms",
]

TF_NORMALIZE_MAP = {
    "m1": "1m",
    "1m": "1m",
    "1min": "1m",
    "5m": "5m",
    "15m": "15m",
    "h1": "1h",
    "1h": "1h",
    "4h": "4h",
    "d1": "1d",
    "1d": "1d",
}


@dataclass
class FileCacheAppendResult:
    inserted: int
    duplicates: int
    total: int
    trimmed: int


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("symbol має бути непорожнім рядком")
    return symbol.upper().replace("/", "").replace(" ", "")


def normalize_tf(tf: str) -> str:
    if not isinstance(tf, str) or not tf.strip():
        raise ValueError("tf має бути непорожнім рядком")
    key = tf.strip().lower()
    if key not in TF_NORMALIZE_MAP:
        raise ValueError(f"TF не підтримується: {tf}")
    return TF_NORMALIZE_MAP[key]


def require_ms_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} має бути int")
    if value < 1_000_000_000_000:
        raise ValueError(f"{field} має бути epoch ms (>=1e12)")
    return int(value)


def validate_geometry(tf: str, open_time_ms: int, close_time_ms: int) -> None:
    tf_ms = TF_TO_MS.get(tf)
    if tf_ms is None:
        raise ValueError(f"TF не підтримується: {tf}")
    if open_time_ms % tf_ms != 0:
        raise ValueError("open_time_ms має бути вирівняний по tf_ms")
    expected_close = open_time_ms + tf_ms - 1
    if close_time_ms != expected_close:
        raise ValueError("close_time_ms має дорівнювати open_time_ms + tf_ms - 1")


def require_float(value: Any, field: str) -> float:
    if value is None:
        raise ValueError(f"{field} має бути числом")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} має бути числом")


def normalize_stream_bar(bar: Dict[str, Any], tf: str) -> Dict[str, Any]:
    open_time = bar.get("open_time_ms", bar.get("open_time"))
    close_time = bar.get("close_time_ms", bar.get("close_time"))
    open_time_ms = require_ms_int(open_time, "open_time_ms")
    close_time_ms = require_ms_int(close_time, "close_time_ms")
    validate_geometry(tf, open_time_ms, close_time_ms)

    complete_val = bar.get("complete")
    if complete_val is not True:
        raise ValueError("cache приймає лише complete=true бари")

    source = str(bar.get("source", "stream"))
    event_ts = bar.get("event_ts_ms", bar.get("event_ts", close_time_ms))
    event_ts_ms = require_ms_int(event_ts, "event_ts_ms")

    return {
        "open_time_ms": open_time_ms,
        "close_time_ms": close_time_ms,
        "open": require_float(bar.get("open"), "open"),
        "high": require_float(bar.get("high"), "high"),
        "low": require_float(bar.get("low"), "low"),
        "close": require_float(bar.get("close"), "close"),
        "volume": float(bar.get("volume", 0.0)),
        "complete": True,
        "synthetic": bool(bar.get("synthetic", False)),
        "source": source,
        "event_ts_ms": event_ts_ms,
    }


def ensure_sorted_unique(rows: List[Dict[str, Any]]) -> None:
    seen = set()
    last_open = None
    for row in rows:
        open_ms = int(row.get("open_time_ms", 0))
        if open_ms in seen:
            raise ValueError("cache має містити UNIQUE(open_time_ms)")
        seen.add(open_ms)
        if last_open is not None and open_ms < last_open:
            raise ValueError("cache має бути відсортований за open_time_ms")
        last_open = open_ms


def merge_rows(
    existing: Iterable[Dict[str, Any]],
    incoming: Iterable[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int]:
    merged: Dict[int, Dict[str, Any]] = {}
    for row in existing:
        merged[int(row["open_time_ms"])] = dict(row)
    duplicates = 0
    for row in incoming:
        open_ms = int(row["open_time_ms"])
        if open_ms in merged:
            duplicates += 1
            continue
        merged[open_ms] = dict(row)
    rows = list(merged.values())
    rows.sort(key=lambda r: int(r["open_time_ms"]))
    return rows, duplicates


def trim_rows(rows: List[Dict[str, Any]], max_bars: int) -> Tuple[List[Dict[str, Any]], int]:
    if max_bars <= 0 or len(rows) <= max_bars:
        return rows, 0
    trimmed = len(rows) - max_bars
    return rows[-max_bars:], trimmed
