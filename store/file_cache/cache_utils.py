from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.time.buckets import TF_TO_MS

CACHE_VERSION = 1
CACHE_COLUMNS = [
    "symbol",
    "tf",
    "open_time_ms",
    "close_time_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "tick_count",
]

MIN_EPOCH_MS = 1_000_000_000_000
MAX_EPOCH_MS = 9_999_999_999_999

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
    if value < MIN_EPOCH_MS or value > MAX_EPOCH_MS:
        raise ValueError(f"{field} має бути epoch ms у межах [{MIN_EPOCH_MS}, {MAX_EPOCH_MS}]")
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
    if close_time_ms <= open_time_ms:
        raise ValueError("close_time_ms має бути > open_time_ms")


def require_float(value: Any, field: str) -> float:
    if value is None:
        raise ValueError(f"{field} має бути числом")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} має бути числом")


def normalize_complete_bar(symbol: str, tf: str, bar: Dict[str, Any]) -> Dict[str, Any]:
    open_time = bar.get("open_time_ms", bar.get("open_time"))
    close_time = bar.get("close_time_ms", bar.get("close_time"))
    open_time_ms = require_ms_int(open_time, "open_time_ms")
    close_time_ms = require_ms_int(close_time, "close_time_ms")
    validate_geometry(tf, open_time_ms, close_time_ms)

    complete_val = bar.get("complete")
    if complete_val is not True:
        raise ValueError("cache приймає лише complete=true бари")

    tick_count = bar.get("tick_count")
    tick_count_val = int(tick_count) if tick_count is not None else 0
    if tick_count_val < 0:
        raise ValueError("tick_count має бути >= 0")

    return {
        "symbol": normalize_symbol(symbol),
        "tf": normalize_tf(tf),
        "open_time_ms": open_time_ms,
        "close_time_ms": close_time_ms,
        "open": require_float(bar.get("open"), "open"),
        "high": require_float(bar.get("high"), "high"),
        "low": require_float(bar.get("low"), "low"),
        "close": require_float(bar.get("close"), "close"),
        "volume": float(bar.get("volume", 0.0)),
        "tick_count": tick_count_val,
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


def merge_rows_keep_last(
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
        merged[open_ms] = dict(row)
    rows = list(merged.values())
    rows.sort(key=lambda r: int(r["open_time_ms"]))
    return rows, duplicates


def trim_rows(rows: List[Dict[str, Any]], max_bars: int) -> Tuple[List[Dict[str, Any]], int]:
    if max_bars <= 0 or len(rows) <= max_bars:
        return rows, 0
    trimmed = len(rows) - max_bars
    return rows[-max_bars:], trimmed


def atomic_write_text(path: Path, content: str) -> None:
    tmp = Path(str(path) + f".tmp.{os.getpid()}")
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(path))


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, content)


def atomic_write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    tmp = Path(str(path) + f".tmp.{os.getpid()}")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CACHE_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    os.replace(str(tmp), str(path))


def json_dumps(payload: Dict[str, Any], indent: Optional[int] = None) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=indent)
