from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from core.time.buckets import TF_TO_MS

TF_ALLOWLIST = {"1m", "5m", "15m", "1h", "4h", "1d"}


@dataclass
class LiveArchiveInsertResult:
    status: str  # INSERTED | DUPLICATE | FAILED
    error: Optional[str] = None


@dataclass
class SqliteLiveArchiveStore:
    """LiveArchive SQLite store (append-only, evidence)."""

    db_path: Path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        return conn

    def init_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS live_archive_bars (
                  symbol TEXT NOT NULL,
                  tf TEXT NOT NULL,
                  open_time_ms INTEGER NOT NULL,
                  close_time_ms INTEGER NOT NULL,
                  payload_json TEXT NOT NULL,
                  ingest_ts_ms INTEGER NOT NULL,
                  PRIMARY KEY(symbol, tf, open_time_ms)
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    def insert_bar(
        self,
        symbol: str,
        tf: str,
        open_time_ms: int,
        close_time_ms: int,
        payload: Dict[str, Any],
        ingest_ts_ms: Optional[int] = None,
    ) -> LiveArchiveInsertResult:
        try:
            self._validate_bar(symbol, tf, open_time_ms, close_time_ms)
        except Exception as exc:  # noqa: BLE001
            return LiveArchiveInsertResult(status="FAILED", error=str(exc))

        if ingest_ts_ms is None:
            ingest_ts_ms = int(time.time() * 1000)
        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

        conn = self.connect()
        try:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO live_archive_bars (
                  symbol, tf, open_time_ms, close_time_ms, payload_json, ingest_ts_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(symbol),
                    str(tf),
                    int(open_time_ms),
                    int(close_time_ms),
                    payload_json,
                    int(ingest_ts_ms),
                ),
            )
            conn.commit()
            if cur.rowcount == 1:
                return LiveArchiveInsertResult(status="INSERTED")
            return LiveArchiveInsertResult(status="DUPLICATE")
        except Exception as exc:  # noqa: BLE001
            return LiveArchiveInsertResult(status="FAILED", error=str(exc))
        finally:
            conn.close()

    def _validate_bar(self, symbol: str, tf: str, open_time_ms: int, close_time_ms: int) -> None:
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("symbol має бути непорожнім рядком")
        if tf not in TF_ALLOWLIST:
            raise ValueError(f"TF не дозволено: {tf}")
        if not isinstance(open_time_ms, int) or isinstance(open_time_ms, bool):
            raise ValueError("open_time_ms має бути int")
        if not isinstance(close_time_ms, int) or isinstance(close_time_ms, bool):
            raise ValueError("close_time_ms має бути int")
        tf_ms = TF_TO_MS.get(tf)
        if tf_ms is None:
            raise ValueError(f"TF не підтримується: {tf}")
        if open_time_ms % tf_ms != 0:
            raise ValueError("open_time_ms має бути вирівняний по tf_ms")
        expected_close = open_time_ms + tf_ms - 1
        if close_time_ms != expected_close:
            raise ValueError("close_time_ms має дорівнювати open_time_ms + tf_ms - 1")
