from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from config.config import Config
from core.time.timestamps import to_epoch_ms_utc
from core.validation.validator import ContractError
from observability.metrics import Metrics
from runtime.fxcm.history_budget import HistoryBudget, build_history_budget
from runtime.fxcm_forexconnect import _try_import_forexconnect, denormalize_symbol
from runtime.history_provider import HistoryProvider
from runtime.status import StatusManager


class FxcmHistoryAdapter:
    """Низькорівневий адаптер FXCM history (1m)."""

    def fetch_1m(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, Any]]:
        raise NotImplementedError


class FxcmForexConnectHistoryAdapter(FxcmHistoryAdapter):
    """FXCM ForexConnect history adapter (1m)."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def is_ready(self) -> Tuple[bool, str]:
        if self._config.fxcm_backend != "forexconnect":
            return False, "fxcm_backend_not_forexconnect"
        if not self._config.fxcm_username or not self._config.fxcm_password:
            return False, "fxcm_secrets_missing"
        fx_class, err = _try_import_forexconnect()
        if fx_class is None:
            return False, f"fxcm_sdk_missing: {err or 'unknown'}"
        return True, ""

    def fetch_1m(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, Any]]:
        ready, reason = self.is_ready()
        if not ready:
            raise ContractError(reason or "fxcm_history_not_ready")
        fx_class, err = _try_import_forexconnect()
        if fx_class is None:
            raise ContractError(f"fxcm_sdk_missing: {err or 'unknown'}")
        fx = fx_class()
        instrument = denormalize_symbol(symbol)
        start_dt = datetime.fromtimestamp(start_ms / 1000.0, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_ms / 1000.0, tz=timezone.utc)
        try:
            fx.login(
                self._config.fxcm_username,
                self._config.fxcm_password,
                self._config.fxcm_host_url,
                self._config.fxcm_connection,
                "",
                "",
            )
            history = fx.get_history(instrument, "m1", start_dt, end_dt)
            rows = list(history) if history is not None else []
            return _rows_to_bars(symbol, rows, limit)
        except Exception as exc:  # noqa: BLE001
            raise ContractError(f"fxcm history fetch failed: {exc}")
        finally:
            try:
                fx.logout()
            except Exception:
                pass


def _row_value(row: Any, keys: Iterable[str]) -> Any:
    for key in keys:
        value = getattr(row, key, None)
        if value is None and isinstance(row, dict):
            value = row.get(key)
        if value is not None:
            return value
    return None


def _to_ms(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        val = int(value)
        if val < 10**11:
            return int(val * 1000)
        return val
    if isinstance(value, datetime):
        return int(value.astimezone(timezone.utc).timestamp() * 1000)
    try:
        return int(to_epoch_ms_utc(value))
    except Exception:
        return None


def _rows_to_bars(symbol: str, rows: Iterable[Any], limit: int) -> List[Dict[str, Any]]:
    bars: List[Dict[str, Any]] = []
    for row in rows:
        if len(bars) >= limit:
            break
        open_time_raw = _row_value(row, ["open_time", "time", "timestamp", "date", "open_time_utc"])
        open_time_ms = _to_ms(open_time_raw)
        if open_time_ms is None:
            continue
        close_time_raw = _row_value(row, ["close_time", "time_close", "close_time_utc"])
        close_time_ms = _to_ms(close_time_raw) if close_time_raw is not None else None
        if close_time_ms is None:
            close_time_ms = int(open_time_ms) + 60_000 - 1
        open_val = _row_value(row, ["open", "bidopen", "askopen"])
        high_val = _row_value(row, ["high", "bidhigh", "askhigh"])
        low_val = _row_value(row, ["low", "bidlow", "asklow"])
        close_val = _row_value(row, ["close", "bidclose", "askclose"])
        if open_val is None or high_val is None or low_val is None or close_val is None:
            continue
        volume = _row_value(row, ["volume", "vol", "tick_volume"])
        bar = {
            "symbol": symbol,
            "open_time_ms": int(open_time_ms),
            "close_time_ms": int(close_time_ms),
            "open": float(open_val),
            "high": float(high_val),
            "low": float(low_val),
            "close": float(close_val),
            "volume": float(volume) if volume is not None else 0.0,
            "complete": 1,
            "synthetic": 0,
            "source": "history",
            "event_ts_ms": int(close_time_ms),
        }
        bars.append(bar)
    return bars


@dataclass
class FxcmHistoryProvider(HistoryProvider):
    """FXCM history provider з жорстким rail TF=1m."""

    adapter: FxcmHistoryAdapter
    budget: Optional[HistoryBudget] = None
    status: Optional[StatusManager] = None
    metrics: Optional[Metrics] = None
    chunk_minutes: int = 360
    probe_minutes: int = 5
    min_sleep_ms: int = 0
    history_ready: bool = True
    history_not_ready_reason: str = ""
    history_retry_after_ms: int = 0
    history_backoff_ms: int = 60_000
    history_backoff_max_ms: int = 15 * 60_000

    def fetch_1m_final(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, Any]]:
        if end_ms < start_ms:
            raise ContractError("history range має бути коректним")
        chunk_ms = max(60_000, int(self.chunk_minutes) * 60 * 1000)
        range_ms = end_ms - start_ms
        if range_ms > chunk_ms:
            self._probe_first(symbol, start_ms, end_ms, limit)
        rows: List[Dict[str, Any]] = []
        t = start_ms
        last_req_ms = 0
        while t <= end_ms:
            chunk_end = min(t + chunk_ms - 1, end_ms)
            if self.min_sleep_ms > 0 and last_req_ms > 0:
                elapsed_ms = int(time.time() * 1000) - last_req_ms
                if elapsed_ms < self.min_sleep_ms:
                    time.sleep((self.min_sleep_ms - elapsed_ms) / 1000.0)
            rows.extend(self._fetch_chunk(symbol, t, chunk_end, limit))
            last_req_ms = int(time.time() * 1000)
            t = chunk_end + 60_000
        return rows

    def fetch_history(self, symbol: str, tf: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, Any]]:
        if tf != "1m":
            raise ContractError("history TF дозволений лише 1m")
        return self.fetch_1m_final(symbol, start_ms, end_ms, limit)

    def is_history_ready(self) -> Tuple[bool, str]:
        if isinstance(self.adapter, FxcmForexConnectHistoryAdapter):
            return self.adapter.is_ready()
        return bool(self.history_ready), str(self.history_not_ready_reason or "")

    def should_backoff(self, now_ms: int) -> bool:
        return int(now_ms) < int(self.history_retry_after_ms or 0)

    def note_not_ready(self, now_ms: int, reason: str) -> int:
        if reason:
            self.history_not_ready_reason = str(reason)
        if int(self.history_retry_after_ms or 0) > int(now_ms):
            return int(self.history_retry_after_ms)
        if int(self.history_retry_after_ms or 0) <= 0:
            backoff_ms = int(self.history_backoff_ms)
        else:
            backoff_ms = min(int(self.history_backoff_ms) * 2, int(self.history_backoff_max_ms))
        self.history_backoff_ms = int(backoff_ms)
        self.history_retry_after_ms = int(now_ms) + int(backoff_ms)
        return int(self.history_retry_after_ms)

    def _probe_first(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> None:
        probe_ms = max(60_000, int(self.probe_minutes) * 60 * 1000)
        probe_start = max(start_ms, end_ms - probe_ms + 1)
        try:
            rows = self._fetch_chunk(symbol, probe_start, end_ms, limit)
        except ContractError:
            raise
        if not rows:
            self._append_error(
                code="history_probe_empty",
                severity="error",
                message="history probe повернув 0 барів",
                context={"symbol": symbol, "start_ms": probe_start, "end_ms": end_ms},
                degraded_tag="history_probe_empty",
            )
            raise ContractError("history probe порожній")

    def _fetch_chunk(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, Any]]:
        budget = self.budget or build_history_budget(1)
        try:
            waited = budget.acquire(symbol)
            if self.metrics is not None:
                self.metrics.fxcm_history_inflight.set(1)
                if waited:
                    self.metrics.fxcm_history_throttled_total.inc()
            return self.adapter.fetch_1m(symbol, start_ms, end_ms, limit)
        except ContractError as exc:
            msg = str(exc)
            code = "history_fetch_failed"
            degraded_tag = "history_fetch_failed"
            if "budget" in msg or "inflight" in msg:
                code = "history_budget_exhausted"
                degraded_tag = "history_budget_exhausted"
            self._append_error(
                code=code,
                severity="error",
                message=msg,
                context={"symbol": symbol, "start_ms": start_ms, "end_ms": end_ms},
                degraded_tag=degraded_tag,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            self._append_error(
                code="history_fetch_failed",
                severity="error",
                message=str(exc),
                context={"symbol": symbol, "start_ms": start_ms, "end_ms": end_ms},
                degraded_tag="history_fetch_failed",
            )
            raise ContractError("history fetch failed")
        finally:
            budget.release(symbol)
            if self.metrics is not None:
                self.metrics.fxcm_history_inflight.set(0)

    def _append_error(
        self,
        code: str,
        severity: str,
        message: str,
        context: Dict[str, Any],
        degraded_tag: Optional[str] = None,
    ) -> None:
        if self.status is not None:
            self.status.append_error(code=code, severity=severity, message=message, context=context)
            if degraded_tag:
                self.status.mark_degraded(degraded_tag)
        if self.metrics is not None and self.status is None:
            self.metrics.errors_total.labels(code=code, severity=severity).inc()
