from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.validation.validator import ContractError
from store.file_cache.cache_utils import (
    CACHE_COLUMNS,
    CACHE_VERSION,
    FileCacheAppendResult,
    atomic_write_csv,
    atomic_write_json,
    ensure_sorted_unique,
    merge_rows_keep_last,
    normalize_complete_bar,
    normalize_symbol,
    normalize_tf,
    now_utc_iso,
    require_ms_int,
    trim_rows,
)


@dataclass
class FileCache:
    """v1-style FileCache: CSV + meta.json (SSOT)."""

    root: Path
    max_bars: int
    warmup_bars: int
    strict: bool = True

    def __post_init__(self) -> None:
        if self.max_bars <= 0:
            raise ValueError("max_bars має бути > 0")
        if self.warmup_bars < 0:
            raise ValueError("warmup_bars має бути >= 0")
        self.root.mkdir(parents=True, exist_ok=True)

    def load(self, symbol: str, tf: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        sym = normalize_symbol(symbol)
        tf_norm = normalize_tf(tf)
        meta = self._load_meta(sym, tf_norm)
        rows: List[Dict[str, Any]] = []
        csv_path = self._csv_path(sym, tf_norm)
        if csv_path.exists():
            rows = self._read_csv(csv_path)
        rows.sort(key=lambda r: int(r["open_time_ms"]))
        ensure_sorted_unique(rows)
        return rows, meta

    def append_complete_bars(
        self,
        symbol: str,
        tf: str,
        bars: List[Dict[str, Any]],
        now_utc: Optional[str] = None,
        source: str = "stream_close",
    ) -> FileCacheAppendResult:
        sym = normalize_symbol(symbol)
        tf_norm = normalize_tf(tf)
        now_utc_val = now_utc or now_utc_iso()
        rows, meta = self.load(sym, tf_norm)
        incoming: List[Dict[str, Any]] = []
        for bar in bars:
            bar_payload = dict(bar)
            bar_payload["complete"] = True
            if "source" not in bar_payload:
                bar_payload["source"] = source
            incoming.append(normalize_complete_bar(sym, tf_norm, bar_payload))
        merged, duplicates = merge_rows_keep_last(rows, incoming)
        merged, trimmed = trim_rows(merged, self.max_bars)
        ensure_sorted_unique(merged)
        inserted = max(0, len(merged) - len(rows))
        meta = self._build_meta(merged, meta, now_utc_val, sym, tf_norm)
        self._save(sym, tf_norm, merged, meta)
        return FileCacheAppendResult(
            inserted=inserted,
            duplicates=duplicates,
            total=len(merged),
            trimmed=trimmed,
        )

    def query(
        self,
        symbol: str,
        tf: str,
        *,
        limit: int,
        since_open_ms: Optional[int] = None,
        until_open_ms: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        rows, _meta = self.load(symbol, tf)
        result: List[Dict[str, Any]] = []
        for row in rows:
            open_ms = int(row["open_time_ms"])
            if since_open_ms is not None and open_ms < since_open_ms:
                continue
            if until_open_ms is not None and open_ms > until_open_ms:
                continue
            result.append(dict(row))
        if limit <= 0:
            return []
        return result[-limit:]

    def get_warmup_slice(
        self,
        symbol: str,
        tf: str,
        *,
        force: bool,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        rows, meta = self.load(symbol, tf)
        if not rows:
            return []
        max_rows = int(limit or self.warmup_bars or self.max_bars)
        last_published = int(meta.get("last_published_open_time_ms", 0))
        if force or last_published <= 0:
            return rows[-max_rows:]
        slice_rows = [row for row in rows if int(row["open_time_ms"]) > last_published]
        return slice_rows[-max_rows:]

    def mark_published(self, symbol: str, tf: str, last_open_time_ms: int, now_utc: Optional[str] = None) -> None:
        sym = normalize_symbol(symbol)
        tf_norm = normalize_tf(tf)
        last_open = require_ms_int(last_open_time_ms, "last_open_time_ms")
        rows, meta = self.load(sym, tf_norm)
        meta["last_published_open_time_ms"] = int(last_open)
        meta["last_refresh_utc"] = now_utc or now_utc_iso()
        self._save(sym, tf_norm, rows, meta)

    def summary(self, symbol: str, tf: str) -> Dict[str, Any]:
        rows, meta = self.load(symbol, tf)
        last_close = int(meta.get("last_close_time_ms", 0))
        return {
            "symbol": normalize_symbol(symbol),
            "tf": normalize_tf(tf),
            "rows": len(rows),
            "last_close_time_ms": last_close,
        }

    def _csv_path(self, symbol: str, tf: str) -> Path:
        return self.root / f"{symbol}_{tf}.csv"

    def _meta_path(self, symbol: str, tf: str) -> Path:
        return self.root / f"{symbol}_{tf}.meta.json"

    def _read_csv(self, path: Path) -> List[Dict[str, Any]]:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None or list(reader.fieldnames) != CACHE_COLUMNS:
                if self.strict:
                    raise ContractError("CSV header не відповідає CACHE_COLUMNS")
                return []
            rows: List[Dict[str, Any]] = []
            for row in reader:
                rows.append(
                    {
                        "symbol": str(row.get("symbol", "")),
                        "tf": str(row.get("tf", "")),
                        "open_time_ms": int(row.get("open_time_ms", 0)),
                        "close_time_ms": int(row.get("close_time_ms", 0)),
                        "open": float(row.get("open", 0.0)),
                        "high": float(row.get("high", 0.0)),
                        "low": float(row.get("low", 0.0)),
                        "close": float(row.get("close", 0.0)),
                        "volume": float(row.get("volume", 0.0)),
                        "tick_count": int(row.get("tick_count", 0)),
                    }
                )
        return rows

    def _load_meta(self, symbol: str, tf: str) -> Dict[str, Any]:
        path = self._meta_path(symbol, tf)
        if not path.exists():
            return self._default_meta()
        meta = json.loads(path.read_text(encoding="utf-8"))
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
            "last_refresh_utc": "",
            "last_stream_heartbeat_utc": "",
            "last_published_open_time_ms": 0,
        }

    def _build_meta(
        self,
        rows: List[Dict[str, Any]],
        prev: Dict[str, Any],
        now_utc: str,
        symbol: str,
        tf: str,
    ) -> Dict[str, Any]:
        last_close = int(rows[-1]["close_time_ms"]) if rows else 0
        last_published = int(prev.get("last_published_open_time_ms", 0))
        return {
            "version": CACHE_VERSION,
            "rows": len(rows),
            "last_close_time_ms": last_close,
            "last_refresh_utc": now_utc,
            "last_stream_heartbeat_utc": now_utc,
            "last_published_open_time_ms": last_published,
            "symbol": symbol,
            "tf": tf,
        }

    def _save(self, symbol: str, tf: str, rows: List[Dict[str, Any]], meta: Dict[str, Any]) -> None:
        csv_path = self._csv_path(symbol, tf)
        meta_path = self._meta_path(symbol, tf)
        atomic_write_csv(csv_path, rows)
        atomic_write_json(meta_path, meta)
