from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from store.sqlite_store import SQLiteStore


@dataclass
class BarsStoreSQLite:
    """SQLite SSOT store для 1m final (P3, мінімальний API)."""

    db_path: Path
    schema_path: Path

    def _store(self) -> SQLiteStore:
        return SQLiteStore(db_path=self.db_path)

    def open(self) -> sqlite3.Connection:
        return self._store().connect()

    def migrate(self) -> None:
        self._store().init_schema(self.schema_path)

    def upsert_bar(
        self,
        symbol: str,
        tf: str,
        open_time_ms: int,
        close_time_ms: int,
        open_p: float,
        high: float,
        low: float,
        close_p: float,
        volume: float,
        complete: bool,
        synthetic: bool,
        source: str,
    ) -> int:
        if tf != "1m":
            raise ValueError("TF не підтримується для P3: " + tf)
        bar = {
            "symbol": symbol,
            "open_time_ms": int(open_time_ms),
            "close_time_ms": int(close_time_ms),
            "open": float(open_p),
            "high": float(high),
            "low": float(low),
            "close": float(close_p),
            "volume": float(volume),
            "complete": 1 if complete else 0,
            "synthetic": 1 if synthetic else 0,
            "source": source,
            "event_ts_ms": int(close_time_ms),
            "ingest_ts_ms": int(time.time() * 1000),
        }
        return self._store().upsert_1m_final(symbol, [bar])

    def get_tail(self, symbol: str, tf: str, window_hours: int) -> List[Dict[str, Any]]:
        if tf != "1m":
            raise ValueError("TF не підтримується для P3: " + tf)
        last_close_ms = self.get_last_complete_close_ms(symbol, tf)
        if last_close_ms <= 0:
            return []
        start_ms = last_close_ms - window_hours * 60 * 60 * 1000 + 1
        limit = max(1, window_hours * 60 + 5)
        return self._store().query_range(symbol, start_ms, last_close_ms, limit)

    def query_range(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, Any]]:
        return self._store().query_range(symbol, start_ms, end_ms, limit)

    def get_last_complete_close_ms(self, symbol: str, tf: str) -> int:
        if tf != "1m":
            raise ValueError("TF не підтримується для P3: " + tf)
        return self._store().get_last_complete_close_ms(symbol)

    def count_1m(self, symbol: str) -> int:
        return self._store().count_1m_final(symbol)

    def get_tail_mark(self, symbol: str, tf: str, window_hours: int) -> Optional[Dict[str, Any]]:
        return self._store().get_tail_mark(symbol, tf, window_hours)

    def set_tail_mark(self, mark: Dict[str, Any]) -> None:
        self._store().set_tail_mark(mark)
