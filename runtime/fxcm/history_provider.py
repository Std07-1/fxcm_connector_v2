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
            if history is None:
                rows = []
            elif hasattr(history, "columns") and hasattr(history, "values"):
                try:
                    columns = [str(col) for col in list(history.columns)]
                    rows = [dict(zip(columns, row)) for row in list(history.values)]
                except Exception:
                    rows = []
            elif hasattr(history, "to_dict"):
                try:
                    rows = list(history.to_dict("records"))
                except Exception:
                    rows = list(history)
            else:
                rows = list(history)
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
            if value is None:
                key_lower = str(key).lower()
                for row_key, row_value in row.items():
                    if str(row_key).lower() == key_lower:
                        value = row_value
                        break
        to_dict_fn = getattr(row, "to_dict", None)
        if value is None and callable(to_dict_fn):
            try:
                row_dict = to_dict_fn()
                if isinstance(row_dict, dict):
                    value = row_dict.get(key)
                    if value is None:
                        key_lower = str(key).lower()
                        for row_key, row_value in row_dict.items():
                            if str(row_key).lower() == key_lower:
                                value = row_value
                                break
            except Exception:
                value = None
        if value is not None:
            return value
    return None


def _coerce_row_dict(row: Any) -> Any:
    if isinstance(row, dict):
        return row
    tolist_fn = getattr(row, "tolist", None)
    if callable(tolist_fn):
        try:
            row_list = tolist_fn()
            if isinstance(row_list, (list, tuple)):
                row = list(row_list)
        except Exception:
            pass
    if isinstance(row, (list, tuple)):
        seq = list(row)
        if len(seq) >= 10:
            return {
                "date": seq[0],
                "bidopen": seq[1],
                "bidhigh": seq[2],
                "bidlow": seq[3],
                "bidclose": seq[4],
                "askopen": seq[5],
                "askhigh": seq[6],
                "asklow": seq[7],
                "askclose": seq[8],
                "volume": seq[9],
            }
        if len(seq) >= 6:
            return {
                "date": seq[0],
                "open": seq[1],
                "high": seq[2],
                "low": seq[3],
                "close": seq[4],
                "volume": seq[5],
            }
    return row


def _row_keys(row: Any) -> List[str]:
    if isinstance(row, dict):
        return [str(key) for key in row.keys()]
    to_dict_fn = getattr(row, "to_dict", None)
    if callable(to_dict_fn):
        try:
            row_dict = to_dict_fn()
            if isinstance(row_dict, dict):
                return [str(key) for key in row_dict.keys()]
        except Exception:
            pass
    if hasattr(row, "keys"):
        try:
            return [str(key) for key in row.keys()]
        except Exception:
            pass
    try:
        return [str(key) for key in vars(row).keys()]
    except Exception:
        return []


def _row_evidence(row: Any) -> str:
    row_type = type(row).__name__
    try:
        row_keys = _row_keys(row)
    except Exception:
        row_keys = []
    keys_trim = row_keys[:20]
    keys_suffix = "" if len(row_keys) <= 20 else f"(+{len(row_keys) - 20})"
    try:
        row_repr = repr(row)
    except Exception:
        row_repr = "<repr_error>"
    if len(row_repr) > 400:
        row_repr = row_repr[:400] + "..."
    try:
        dir_items = [
            name
            for name in dir(row)
            if any(key in name.lower() for key in ["date", "time", "bid", "ask", "open", "high", "low", "close", "vol"])
        ]
    except Exception:
        dir_items = []
    dir_trim = dir_items[:20]
    dir_suffix = "" if len(dir_items) <= 20 else f"(+{len(dir_items) - 20})"
    return (
        f"row_type={row_type} row_keys={keys_trim}{keys_suffix} "
        f"row_repr={row_repr} dir_match={dir_trim}{dir_suffix}"
    )


def _to_ms(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if len(value) == 2 and all(isinstance(item, (int, float)) for item in value):
            return _to_ms(value[0])
        if len(value) == 3 and all(isinstance(item, (int, float)) for item in value):
            return _to_ms(value[0])
    if isinstance(value, (int, float)):
        if isinstance(value, bool):
            return None
        val = int(value)
        if val < 10**11:
            return int(val * 1000)
        if val > 9_999_999_999_999_999:
            return int(val // 1_000_000)
        if val > 9_999_999_999_999:
            return int(val // 1_000)
        return val
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z") and "." in text:
            head, tail = text.split(".", 1)
            digits = "".join(ch for ch in tail if ch.isdigit())
            if digits:
                digits = digits[:6].ljust(6, "0")
                text = f"{head}.{digits}Z"
        elif "." in text:
            head, tail = text.split(".", 1)
            digits = "".join(ch for ch in tail if ch.isdigit())
            if digits:
                digits = digits[:6].ljust(6, "0")
                text = f"{head}.{digits}"
        try:
            return int(to_epoch_ms_utc(text))
        except Exception:
            return None
    to_pydatetime = getattr(value, "to_pydatetime", None)
    if callable(to_pydatetime):
        try:
            return _to_ms(to_pydatetime())
        except Exception:
            return None
    if isinstance(value, datetime):
        return int(value.astimezone(timezone.utc).timestamp() * 1000)
    for attr in ["value", "item"]:
        getter = getattr(value, attr, None)
        if callable(getter):
            try:
                inner = getter()
                if inner is not value:
                    return _to_ms(inner)
            except Exception:
                pass
    try:
        return int(to_epoch_ms_utc(value))
    except Exception:
        return None


def _rows_to_bars(symbol: str, rows: Iterable[Any], limit: int) -> List[Dict[str, Any]]:
    bars: List[Dict[str, Any]] = []
    for row in rows:
        row = _coerce_row_dict(row)
        if len(bars) >= limit:
            break
        open_time_raw = _row_value(
            row,
            [
                "open_time",
                "time",
                "timestamp",
                "date",
                "Date",
                "DATE",
                "datetime",
                "DATETIME",
                "DateTime",
                "Datetime",
                "open_time_utc",
                "date_utc",
                "open_time_ms",
            ],
        )
        if open_time_raw is None:
            row_keys = _row_keys(row)
            evidence = _row_evidence(row)
            raise ContractError(f"history_row_missing_date: row_keys={row_keys} {evidence}")
        open_time_ms = _to_ms(open_time_raw)
        if open_time_ms is None:
            try:
                value_repr = repr(open_time_raw)
            except Exception:
                value_repr = "<repr_error>"
            if len(value_repr) > 400:
                value_repr = value_repr[:400] + "..."
            raise ContractError(
                "history_row_date_invalid: " f"value_type={type(open_time_raw).__name__} value_repr={value_repr}"
            )
        close_time_raw = _row_value(row, ["close_time", "time_close", "close_time_utc"])
        close_time_ms = _to_ms(close_time_raw) if close_time_raw is not None else None
        if close_time_ms is None:
            close_time_ms = int(open_time_ms) + 60_000 - 1
        open_val = _row_value(row, ["open", "bidopen", "askopen", "BidOpen", "AskOpen"])
        high_val = _row_value(row, ["high", "bidhigh", "askhigh", "BidHigh", "AskHigh"])
        low_val = _row_value(row, ["low", "bidlow", "asklow", "BidLow", "AskLow"])
        close_val = _row_value(row, ["close", "bidclose", "askclose", "BidClose", "AskClose"])
        if open_val is None or high_val is None or low_val is None or close_val is None:
            continue
        volume = _row_value(row, ["volume", "vol", "tick_volume", "Volume"])
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
            if waited and self.status is not None:
                self.status.append_error_throttled(
                    code="history_inflight_wait",
                    severity="warning",
                    message="history запит очікує через single in-flight",
                    context={"symbol": symbol, "start_ms": start_ms, "end_ms": end_ms},
                    throttle_key=f"history_inflight_wait:{symbol}",
                    throttle_ms=60_000,
                    now_ms=int(time.time() * 1000),
                )
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
