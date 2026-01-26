from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.validation.validator import ContractError


@dataclass
class SQLiteStore:
    """SQLite SSOT store для 1m final (WAL)."""

    db_path: Path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self, schema_path: Path) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            sql = schema_path.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.commit()
        finally:
            conn.close()

    def init_db(self, schema_path: Path) -> None:
        """Публічний alias для ініціалізації схеми."""
        self.init_schema(schema_path)

    def upsert_bars(self, bars: Iterable[Dict[str, Any]]) -> int:
        conn = self.connect()
        try:
            cur = conn.cursor()
            count = 0
            min_open: Optional[int] = None
            max_close: Optional[int] = None
            symbol_ref: Optional[str] = None
            for bar in bars:
                if bar.get("source") != "history":
                    raise ContractError("1m final має мати source=history")
                if int(bar.get("complete", 1)) != 1:
                    raise ContractError("1m final має мати complete=1")
                if int(bar.get("synthetic", 0)) != 0:
                    raise ContractError("1m final має мати synthetic=0")
                close_time_ms = int(bar["close_time_ms"])
                event_ts_ms = int(bar.get("event_ts_ms", 0))
                if event_ts_ms != close_time_ms:
                    raise ContractError("event_ts_ms має дорівнювати close_time_ms")
                conflict = cur.execute(
                    """
                    SELECT source FROM bars_1m_final
                    WHERE symbol = ? AND open_time_ms = ? AND complete = 1
                      AND source != 'history'
                    """,
                    (bar["symbol"], bar["open_time_ms"]),
                ).fetchone()
                if conflict is not None:
                    raise ContractError("NoMix порушено для 1m final")
                cur.execute(
                    """
                    INSERT OR REPLACE INTO bars_1m_final (
                      symbol, open_time_ms, close_time_ms, open, high, low, close, volume,
                      complete, synthetic, source, event_ts_ms, ingest_ts_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bar["symbol"],
                        bar["open_time_ms"],
                        close_time_ms,
                        bar["open"],
                        bar["high"],
                        bar["low"],
                        bar["close"],
                        bar["volume"],
                        bar["complete"],
                        bar["synthetic"],
                        bar["source"],
                        bar["event_ts_ms"],
                        bar["ingest_ts_ms"],
                    ),
                )
                symbol_ref = str(bar["symbol"])
                open_time_ms = int(bar["open_time_ms"])
                if min_open is None or open_time_ms < min_open:
                    min_open = open_time_ms
                if max_close is None or close_time_ms > max_close:
                    max_close = close_time_ms
                count += 1
            if symbol_ref is not None and min_open is not None and max_close is not None:
                self._invalidate_tail_audit_state_range_conn(
                    conn=conn,
                    symbol=symbol_ref,
                    tf="1m",
                    from_ms=min_open,
                    to_ms=max_close,
                )
            conn.commit()
            return count
        finally:
            conn.close()

    def upsert_1m_final(self, symbol: str, bars: Iterable[Dict[str, Any]]) -> int:
        """Idempotent upsert для 1m final; symbol має бути в кожному bar."""
        return self.upsert_bars(bars)

    def query_range(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, Any]]:
        conn = self.connect()
        try:
            cur = conn.execute(
                """
                SELECT * FROM bars_1m_final
                WHERE symbol = ? AND open_time_ms >= ? AND open_time_ms <= ?
                ORDER BY open_time_ms ASC
                LIMIT ?
                """,
                (symbol, start_ms, end_ms, limit),
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def query_1m_range(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, Any]]:
        """Публічний alias для читання діапазону 1m final."""
        return self.query_range(symbol, start_ms, end_ms, limit)

    def query_tail(self, symbol: str, limit: int) -> List[Dict[str, Any]]:
        conn = self.connect()
        try:
            cur = conn.execute(
                """
                SELECT * FROM bars_1m_final
                WHERE symbol = ?
                ORDER BY open_time_ms DESC
                LIMIT ?
                """,
                (symbol, limit),
            )
            rows = cur.fetchall()
            return [dict(r) for r in reversed(rows)]
        finally:
            conn.close()

    def query_1m_tail(self, symbol: str, limit: int) -> List[Dict[str, Any]]:
        """Публічний alias для читання хвоста 1m final."""
        return self.query_tail(symbol, limit)

    def get_last_complete_close_ms(self, symbol: str) -> int:
        conn = self.connect()
        try:
            cur = conn.execute(
                "SELECT MAX(close_time_ms) AS last_close FROM bars_1m_final WHERE symbol = ?",
                (symbol,),
            )
            row = cur.fetchone()
            if row is None or row["last_close"] is None:
                return 0
            return int(row["last_close"])
        finally:
            conn.close()

    def count_1m_final(self, symbol: str) -> int:
        conn = self.connect()
        try:
            cur = conn.execute(
                "SELECT COUNT(*) AS total FROM bars_1m_final WHERE symbol = ?",
                (symbol,),
            )
            row = cur.fetchone()
            if row is None:
                return 0
            return int(row["total"])
        finally:
            conn.close()

    def get_1m_coverage(self, symbol: str) -> Dict[str, Any]:
        conn = self.connect()
        try:
            cur = conn.execute(
                """
                SELECT MIN(open_time_ms) AS first_open, MAX(close_time_ms) AS last_close, COUNT(*) AS total
                FROM bars_1m_final
                WHERE symbol = ?
                """,
                (symbol,),
            )
            row = cur.fetchone()
            if row is None or row["total"] is None or int(row["total"]) == 0:
                return {
                    "first_open_ms": None,
                    "last_close_ms": None,
                    "bars": 0,
                    "coverage_days": 0,
                }
            first_open = int(row["first_open"])
            last_close = int(row["last_close"])
            bars = int(row["total"])
            span_ms = max(0, last_close - first_open + 1)
            coverage_days = int(span_ms / (24 * 60 * 60 * 1000))
            return {
                "first_open_ms": first_open,
                "last_close_ms": last_close,
                "bars": bars,
                "coverage_days": max(0, coverage_days),
            }
        finally:
            conn.close()

    def upsert_htf_final(self, symbol: str, tf: str, bars: Iterable[Dict[str, Any]]) -> int:
        """Idempotent upsert для HTF final з NoMix rail."""
        conn = self.connect()
        try:
            cur = conn.cursor()
            count = 0
            min_open: Optional[int] = None
            max_close: Optional[int] = None
            for bar in bars:
                if bar.get("source") != "history_agg":
                    raise ContractError("HTF final має мати source=history_agg")
                open_time_ms = int(bar["open_time_ms"])
                conflict = cur.execute(
                    """
                    SELECT source FROM bars_htf_final
                    WHERE symbol = ? AND tf = ? AND open_time_ms = ? AND complete = 1
                      AND source != 'history_agg'
                    """,
                    (symbol, tf, open_time_ms),
                ).fetchone()
                if conflict is not None:
                    raise ContractError("NoMix порушено для HTF final")
                cur.execute(
                    """
                    INSERT OR REPLACE INTO bars_htf_final (
                      symbol, tf, open_time_ms, close_time_ms, open, high, low, close, volume,
                      complete, synthetic, source, event_ts_ms, ingest_ts_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        tf,
                        bar["open_time_ms"],
                        bar["close_time_ms"],
                        bar["open"],
                        bar["high"],
                        bar["low"],
                        bar["close"],
                        bar["volume"],
                        bar["complete"],
                        bar["synthetic"],
                        bar["source"],
                        bar["event_ts_ms"],
                        bar["ingest_ts_ms"],
                    ),
                )
                open_time_ms = int(bar["open_time_ms"])
                close_time_ms = int(bar["close_time_ms"])
                if min_open is None or open_time_ms < min_open:
                    min_open = open_time_ms
                if max_close is None or close_time_ms > max_close:
                    max_close = close_time_ms
                count += 1
            if min_open is not None and max_close is not None:
                self._invalidate_tail_audit_state_range_conn(
                    conn=conn,
                    symbol=symbol,
                    tf=tf,
                    from_ms=min_open,
                    to_ms=max_close,
                )
            conn.commit()
            return count
        finally:
            conn.close()

    def query_htf_range(self, symbol: str, tf: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, Any]]:
        conn = self.connect()
        try:
            cur = conn.execute(
                """
                SELECT * FROM bars_htf_final
                WHERE symbol = ? AND tf = ? AND open_time_ms >= ? AND open_time_ms <= ?
                ORDER BY open_time_ms ASC
                LIMIT ?
                """,
                (symbol, tf, start_ms, end_ms, limit),
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def query_htf_tail(self, symbol: str, tf: str, limit: int) -> List[Dict[str, Any]]:
        conn = self.connect()
        try:
            cur = conn.execute(
                """
                SELECT * FROM bars_htf_final
                WHERE symbol = ? AND tf = ?
                ORDER BY open_time_ms DESC
                LIMIT ?
                """,
                (symbol, tf, limit),
            )
            rows = cur.fetchall()
            return [dict(r) for r in reversed(rows)]
        finally:
            conn.close()

    def trim_retention_days(self, symbol: str, days: int) -> int:
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - days * 24 * 60 * 60 * 1000
        conn = self.connect()
        try:
            cur = conn.execute(
                "DELETE FROM bars_1m_final WHERE symbol = ? AND open_time_ms < ?",
                (symbol, cutoff_ms),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (f"retention_last_purge_ms:{symbol}", str(now_ms)),
            )
            conn.commit()
            return int(cur.rowcount)
        finally:
            conn.close()

    def get_tail_audit_state(self, symbol: str, tf: str) -> Optional[Dict[str, Any]]:
        conn = self.connect()
        try:
            cur = conn.execute(
                """
                SELECT * FROM tail_audit_state
                WHERE symbol = ? AND tf = ?
                """,
                (symbol, tf),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def upsert_tail_audit_state(self, state: Dict[str, Any]) -> None:
        conn = self.connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO tail_audit_state (
                  symbol, tf, verified_from_ms, verified_until_ms,
                  checked_until_close_ms, etag_last_complete_bar_ms,
                  last_audit_ts_ms, updated_ts_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state["symbol"],
                    state["tf"],
                    state["verified_from_ms"],
                    state["verified_until_ms"],
                    state.get("checked_until_close_ms", 0),
                    state["etag_last_complete_bar_ms"],
                    state["last_audit_ts_ms"],
                    state["updated_ts_ms"],
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def invalidate_tail_audit_state_range(self, symbol: str, tf: str, from_ms: int, to_ms: int) -> None:
        if from_ms <= 0 or to_ms <= 0 or from_ms > to_ms:
            raise ValueError("Некоректний діапазон для invalidation")
        conn = self.connect()
        try:
            self._invalidate_tail_audit_state_range_conn(conn, symbol, tf, from_ms, to_ms)
            conn.commit()
        finally:
            conn.close()

    def _invalidate_tail_audit_state_range_conn(
        self,
        conn: sqlite3.Connection,
        symbol: str,
        tf: str,
        from_ms: int,
        to_ms: int,
    ) -> None:
        cur = conn.execute(
            """
            SELECT * FROM tail_audit_state
            WHERE symbol = ? AND tf = ?
            """,
            (symbol, tf),
        )
        row = cur.fetchone()
        if row is None:
            return
        verified_from = int(row["verified_from_ms"])
        verified_until = int(row["verified_until_ms"])
        if verified_from <= 0 or verified_until <= 0:
            return
        if to_ms < verified_from or from_ms > verified_until:
            return
        now_ms = int(time.time() * 1000)
        new_from = verified_from
        new_until = verified_until
        if "checked_until_close_ms" in row.keys():
            new_checked_until = int(row["checked_until_close_ms"])
        else:
            new_checked_until = 0
        if from_ms <= verified_from:
            new_from = 0
            new_until = 0
            new_checked_until = 0
        else:
            new_until = min(verified_until, from_ms - 1)
            if new_until < new_from:
                new_from = 0
                new_until = 0
                new_checked_until = 0
        if new_checked_until > 0 and new_until > 0 and new_checked_until > new_until:
            new_checked_until = new_until
        conn.execute(
            """
            UPDATE tail_audit_state
            SET verified_from_ms = ?, verified_until_ms = ?, checked_until_close_ms = ?, updated_ts_ms = ?
            WHERE symbol = ? AND tf = ?
            """,
            (new_from, new_until, new_checked_until, now_ms, symbol, tf),
        )

    def get_meta(self, key: str) -> Optional[str]:
        conn = self.connect()
        try:
            cur = conn.execute("SELECT value FROM meta WHERE key = ?", (key,))
            row = cur.fetchone()
            if row is None:
                return None
            return str(row["value"])
        finally:
            conn.close()

    def set_meta(self, key: str, value: str) -> None:
        conn = self.connect()
        try:
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
        finally:
            conn.close()

    def get_tail_mark(self, symbol: str, tf: str, window_hours: int) -> Optional[Dict[str, Any]]:
        conn = self.connect()
        try:
            cur = conn.execute(
                """
                SELECT * FROM tail_audit_marks
                WHERE symbol = ? AND tf = ? AND window_hours = ?
                """,
                (symbol, tf, window_hours),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def set_tail_mark(self, mark: Dict[str, Any]) -> None:
        conn = self.connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO tail_audit_marks (
                  symbol, tf, window_hours, checked_at_ms, status,
                  missing_bars, next_allowed_check_ms
                                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mark["symbol"],
                    mark["tf"],
                    mark["window_hours"],
                    mark["checked_at_ms"],
                    mark["status"],
                    mark["missing_bars"],
                    mark["next_allowed_check_ms"],
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_republish_mark(self, symbol: str, tf: str, window_hours: int) -> Optional[Dict[str, Any]]:
        conn = self.connect()
        try:
            cur = conn.execute(
                """
                SELECT * FROM republish_marks
                WHERE symbol = ? AND tf = ? AND window_hours = ?
                """,
                (symbol, tf, window_hours),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def set_republish_mark(self, mark: Dict[str, Any]) -> None:
        conn = self.connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO republish_marks (
                  symbol, tf, window_hours, last_republish_ts_ms,
                  next_allowed_republish_ms, forced
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    mark["symbol"],
                    mark["tf"],
                    mark["window_hours"],
                    mark["last_republish_ts_ms"],
                    mark["next_allowed_republish_ms"],
                    mark["forced"],
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_mark(self, symbol: str, tf: str, window_hours: int) -> Optional[Dict[str, Any]]:
        """Зворотна сумісність з попереднім API."""
        return self.get_tail_mark(symbol, tf, window_hours)

    def set_mark(self, mark: Dict[str, Any]) -> None:
        """Зворотна сумісність з попереднім API."""
        self.set_tail_mark(mark)

    def upsert_mark(self, mark: Dict[str, Any]) -> None:
        """Зворотна сумісність з попереднім API."""
        self.set_tail_mark(mark)
