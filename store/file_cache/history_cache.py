from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.validation.validator import ContractError
from store.file_cache.cache_utils import (
    CACHE_COLUMNS,
    CACHE_VERSION,
    FileCacheAppendResult,
    ensure_sorted_unique,
    merge_rows,
    normalize_stream_bar,
    normalize_symbol,
    normalize_tf,
    now_utc_iso,
    trim_rows,
)


@dataclass
class HistoryCache:
    """File cache: CSV + meta.json (SSOT)."""

    root: Path
    symbol: str
    tf: str
    max_bars: int
    warmup_bars: int = 0
    _rows: List[Dict[str, Any]] = field(default_factory=list)
    _pending: List[Dict[str, Any]] = field(default_factory=list)
    _meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.symbol = normalize_symbol(self.symbol)
        self.tf = normalize_tf(self.tf)
        if self.max_bars <= 0:
            raise ValueError("max_bars має бути > 0")
        if self.warmup_bars < 0:
            raise ValueError("warmup_bars має бути >= 0")
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def csv_path(self) -> Path:
        return self.root / f"{self.symbol}_{self.tf}.csv"

    @property
    def meta_path(self) -> Path:
        return self.root / f"{self.symbol}_{self.tf}.meta.json"

    def load(self) -> List[Dict[str, Any]]:
        self._rows = []
        self._pending = []
        self._meta = self._load_meta()
        if self.csv_path.exists():
            with self.csv_path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                if reader.fieldnames is None or list(reader.fieldnames) != CACHE_COLUMNS:
                    raise ContractError("CSV header не відповідає CACHE_COLUMNS")
                for row in reader:
                    self._rows.append(self._parse_row(row))
        self._rows.sort(key=lambda r: int(r["open_time_ms"]))
        ensure_sorted_unique(self._rows)
        if self.warmup_bars > 0 and len(self._rows) > self.warmup_bars:
            self._rows = self._rows[-self.warmup_bars :]
        return list(self._rows)

    def append_bars(self, bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for bar in bars:
            normalized = normalize_stream_bar(bar, tf=self.tf)
            self._pending.append(normalized)
        return list(self._pending)

    def merge_and_trim(self, max_bars: Optional[int] = None) -> FileCacheAppendResult:
        effective_max = int(max_bars or self.max_bars)
        merged, duplicates = merge_rows(self._rows, self._pending)
        merged, trimmed = trim_rows(merged, effective_max)
        ensure_sorted_unique(merged)
        inserted = max(0, len(merged) - len(self._rows))
        self._rows = merged
        self._pending = []
        return FileCacheAppendResult(
            inserted=inserted,
            duplicates=duplicates,
            total=len(self._rows),
            trimmed=trimmed,
        )

    def save(self, now_ms: Optional[int] = None) -> None:
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        self._meta = self._build_meta(now_ms)
        with self.csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CACHE_COLUMNS)
            writer.writeheader()
            for row in self._rows:
                writer.writerow(row)
        self.meta_path.write_text(json.dumps(self._meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def append_stream_bars(self, bars: List[Dict[str, Any]]) -> FileCacheAppendResult:
        if not bars:
            return FileCacheAppendResult(inserted=0, duplicates=0, total=len(self._rows), trimmed=0)
        self.load()
        self.append_bars(bars)
        result = self.merge_and_trim()
        self.save()
        return result

    def _parse_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return {
                "open_time_ms": int(row["open_time_ms"]),
                "close_time_ms": int(row["close_time_ms"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "complete": str(row["complete"]).lower() in {"1", "true", "yes"},
                "synthetic": str(row["synthetic"]).lower() in {"1", "true", "yes"},
                "source": str(row["source"]),
                "event_ts_ms": int(row["event_ts_ms"]),
            }
        except Exception as exc:  # noqa: BLE001
            raise ContractError(f"CSV row невалідний: {exc}") from exc

    def _load_meta(self) -> Dict[str, Any]:
        if not self.meta_path.exists():
            return self._default_meta()
        raw = self.meta_path.read_text(encoding="utf-8")
        meta = json.loads(raw)
        if not isinstance(meta, dict):
            raise ContractError("meta.json має бути JSON-об'єктом")
        version = int(meta.get("version", 0))
        if version != CACHE_VERSION:
            raise ContractError("meta.version не підтримується")
        return meta

    def _default_meta(self) -> Dict[str, Any]:
        return {
            "version": CACHE_VERSION,
            "rows": 0,
            "last_close_time_ms": 0,
            "last_refresh_utc": now_utc_iso(),
            "last_stream_heartbeat": 0,
            "last_published_open_time_ms": 0,
        }

    def _build_meta(self, now_ms: int) -> Dict[str, Any]:
        last_close = int(self._rows[-1]["close_time_ms"]) if self._rows else 0
        last_open = int(self._rows[-1]["open_time_ms"]) if self._rows else 0
        return {
            "version": CACHE_VERSION,
            "rows": len(self._rows),
            "last_close_time_ms": last_close,
            "last_refresh_utc": now_utc_iso(),
            "last_stream_heartbeat": int(now_ms),
            "last_published_open_time_ms": last_open,
        }
