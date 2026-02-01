from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Tuple

from typing_extensions import Protocol

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from observability.metrics import Metrics

STATUS_PUBSUB_MAX_BYTES = 8192
STATUS_ERRORS_MAX = 20
STATUS_DEGRADED_MAX = 20
STATUS_DERIVED_TFS_MAX = 10
STATUS_DERIVED_ERRORS_MAX = 10


class PublisherProtocol(Protocol):
    """Мінімальний контракт публікатора для статусу."""

    def set_snapshot(self, key: str, json_str: str) -> None: ...

    def publish(self, channel: str, json_str: str) -> None: ...


def _now_ms() -> int:
    return int(time.time() * 1000)


def _trim_list(values: Any, max_len: int) -> List[Any]:
    if not isinstance(values, list):
        return []
    if max_len <= 0:
        return []
    if len(values) <= max_len:
        return list(values)
    return list(values[-max_len:])


def _redact_public_message(message: str, max_len: int = 160) -> str:
    text = str(message).replace("\r", " ").replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len]
    return text


def build_status_pubsub_payload(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Будує компактний payload для pubsub/snapshot без великих масивів."""
    payload = {
        "ts": int(snapshot.get("ts", 0)),
        "version": str(snapshot.get("version", "")),
        "schema_version": int(snapshot.get("schema_version", 0)),
        "pipeline_version": str(snapshot.get("pipeline_version", "")),
        "build_version": str(snapshot.get("build_version", "")),
        "process": dict(snapshot.get("process", {})),
        "market": dict(snapshot.get("market", {})),
        "errors": _trim_list(snapshot.get("errors", []), STATUS_ERRORS_MAX),
        "degraded": _trim_list(snapshot.get("degraded", []), STATUS_DEGRADED_MAX),
        "command_bus": dict(snapshot.get("command_bus", {})),
        "last_command": dict(snapshot.get("last_command", {})),
    }

    tail_guard = snapshot.get("tail_guard")
    if isinstance(tail_guard, dict):
        payload["tail_guard_summary"] = _build_tail_guard_summary(tail_guard)

    for key in [
        "price",
        "fxcm",
        "history",
        "ohlcv_preview",
        "ohlcv_final",
        "no_mix",
        "tail_guard",
        "republish",
        "reconcile",
        "bootstrap",
    ]:
        value = snapshot.get(key)
        if isinstance(value, dict):
            payload[key] = dict(value)
            if key == "reconcile" and "last_end_ms" not in payload[key]:
                payload[key]["last_end_ms"] = 0

    derived = snapshot.get("derived_rebuild")
    if isinstance(derived, dict):
        payload["derived_rebuild"] = {
            "last_run_ts_ms": int(derived.get("last_run_ts_ms", 0)),
            "last_range_ms": list(derived.get("last_range_ms", [0, 0])),
            "last_tfs": _trim_list(derived.get("last_tfs", []), STATUS_DERIVED_TFS_MAX),
            "state": str(derived.get("state", "idle")),
            "errors": _trim_list(derived.get("errors", []), STATUS_DERIVED_ERRORS_MAX),
        }
    return payload


def status_payload_size_bytes(payload: Dict[str, Any]) -> int:
    json_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return len(json_str.encode("utf-8"))


def _default_tail_guard_block() -> Dict[str, Any]:
    return {
        "last_audit_ts_ms": 0,
        "window_hours": 0,
        "tf_states": {
            "1m": {"missing_bars": 0, "skipped_by_ttl": False, "state": "idle"},
            "15m": {"missing_bars": 0, "skipped_by_ttl": False, "state": "idle"},
            "1h": {"missing_bars": 0, "skipped_by_ttl": False, "state": "idle"},
            "4h": {"missing_bars": 0, "skipped_by_ttl": False, "state": "idle"},
            "1d": {"missing_bars": 0, "skipped_by_ttl": False, "state": "idle"},
        },
        "marks": {
            "1m": {
                "verified_from_ms": 0,
                "verified_until_ms": 0,
                "checked_until_close_ms": 0,
                "etag_last_complete_bar_ms": 0,
                "last_audit_ts_ms": 0,
            },
            "15m": {
                "verified_from_ms": 0,
                "verified_until_ms": 0,
                "checked_until_close_ms": 0,
                "etag_last_complete_bar_ms": 0,
                "last_audit_ts_ms": 0,
            },
            "1h": {
                "verified_from_ms": 0,
                "verified_until_ms": 0,
                "checked_until_close_ms": 0,
                "etag_last_complete_bar_ms": 0,
                "last_audit_ts_ms": 0,
            },
            "4h": {
                "verified_from_ms": 0,
                "verified_until_ms": 0,
                "checked_until_close_ms": 0,
                "etag_last_complete_bar_ms": 0,
                "last_audit_ts_ms": 0,
            },
            "1d": {
                "verified_from_ms": 0,
                "verified_until_ms": 0,
                "checked_until_close_ms": 0,
                "etag_last_complete_bar_ms": 0,
                "last_audit_ts_ms": 0,
            },
        },
        "repaired": False,
    }


def _default_tail_guard_tf_state_compact() -> Dict[str, Any]:
    return {"status": "idle", "missing_bars": 0, "skipped_by_ttl": False}


def _extract_tail_guard_meta_int(tail: Dict[str, Any], key: str) -> int:
    value = tail.get(key)
    if isinstance(value, int):
        return int(value)
    for tier in ["far", "near"]:
        block = tail.get(tier)
        if isinstance(block, dict):
            tier_value = block.get(key)
            if isinstance(tier_value, int):
                return int(tier_value)
    return 0


def _extract_tail_guard_meta_bool(tail: Dict[str, Any], key: str) -> bool:
    value = tail.get(key)
    if isinstance(value, bool):
        return bool(value)
    for tier in ["far", "near"]:
        block = tail.get(tier)
        if isinstance(block, dict):
            tier_value = block.get(key)
            if isinstance(tier_value, bool):
                return bool(tier_value)
    return False


def _extract_tail_guard_tf_states(tail: Dict[str, Any]) -> Dict[str, Any]:
    tf_states = tail.get("tf_states")
    if isinstance(tf_states, dict):
        return tf_states
    for tier in ["far", "near"]:
        block = tail.get(tier)
        if isinstance(block, dict):
            tier_states = block.get("tf_states")
            if isinstance(tier_states, dict):
                return tier_states
    return {}


def _build_tail_guard_summary(tail: Dict[str, Any]) -> Dict[str, Any]:
    required_tfs = ["1m", "15m", "1h", "4h", "1d"]
    tf_states = _extract_tail_guard_tf_states(tail)
    compact: Dict[str, Any] = {}
    for tf in required_tfs:
        state_obj = tf_states.get(tf)
        if not isinstance(state_obj, dict):
            compact[tf] = _default_tail_guard_tf_state_compact()
            continue
        status = state_obj.get("state")
        if status is None:
            status = state_obj.get("status", "idle")
        compact[tf] = {
            "status": str(status),
            "missing_bars": int(state_obj.get("missing_bars", 0)),
            "skipped_by_ttl": bool(state_obj.get("skipped_by_ttl", False)),
        }
    return {
        "last_audit_ts_ms": _extract_tail_guard_meta_int(tail, "last_audit_ts_ms"),
        "window_hours": _extract_tail_guard_meta_int(tail, "window_hours"),
        "repaired": _extract_tail_guard_meta_bool(tail, "repaired"),
        "tf_states_compact": compact,
    }


@dataclass
class StatusManager:
    """Менеджер status snapshot з in-memory станом."""

    config: Config
    validator: SchemaValidator
    publisher: PublisherProtocol
    calendar: Calendar
    metrics: Optional[Metrics] = None

    def __post_init__(self) -> None:
        self._started_ms = _now_ms()
        self._snapshot: Dict[str, Any] = {}
        self._last_publish_ms = 0
        self._tick_drop_bucket_ms = 0
        self._tick_window: Deque[Tuple[int, int, int]] = deque()
        self._tick_window_seen_total = 0
        self._tick_window_dropped_total = 0
        self._tick_window_ms = 60_000
        self._preview_paused = False
        self._error_throttle_lock = threading.Lock()
        self._error_throttle_last_ts_by_key: Dict[str, int] = {}
        self._error_coalesce_lock = threading.Lock()
        self._error_coalesce_last_ts_by_key: Dict[str, int] = {}

    def _ensure_tail_guard_tiers(self) -> Dict[str, Any]:
        tail = self._snapshot.get("tail_guard")
        if not isinstance(tail, dict):
            tail = _default_tail_guard_block()
        if not isinstance(tail.get("near"), dict):
            tail["near"] = _default_tail_guard_block()
        if not isinstance(tail.get("far"), dict):
            tail["far"] = _default_tail_guard_block()
        self._snapshot["tail_guard"] = tail
        return tail

    def _has_error_code(self, code: str) -> bool:
        errors = self._snapshot.get("errors")
        if not isinstance(errors, list):
            return False
        for err in errors:
            if isinstance(err, dict) and err.get("code") == code:
                return True
        return False

    def _ensure_calendar_health(self, ts_ms: int) -> None:
        calendar_error = self.calendar.health_error()
        if calendar_error:
            self.mark_degraded("calendar_error")
            if not self._has_error_code("calendar_error"):
                self.append_error(
                    code="calendar_error",
                    severity="error",
                    message=calendar_error,
                )

    def _sync_tail_guard_from_block(self, tail: Dict[str, Any], block: Dict[str, Any]) -> None:
        tail["last_audit_ts_ms"] = int(block.get("last_audit_ts_ms", 0))
        tail["window_hours"] = int(block.get("window_hours", 0))
        tail["tf_states"] = dict(block.get("tf_states", {}))
        tail["marks"] = dict(block.get("marks", {}))
        tail["repaired"] = bool(block.get("repaired", False))

    def build_initial_snapshot(self) -> Dict[str, Any]:
        ts_ms = _now_ms()
        command_bus_state = "disabled"
        command_bus_error = None
        if self.config.commands_enabled:
            command_bus_state = "error"
            command_bus_error = {
                "code": "not_started",
                "message": "Command bus ще не запущений",
                "ts": ts_ms,
            }
        fxcm_state = "disabled" if self.config.fxcm_backend == "disabled" else "connecting"
        errors = []
        degraded = []
        calendar_error = self.calendar.health_error()
        if calendar_error:
            degraded.append("calendar_error")
            errors.append(
                {
                    "code": "calendar_error",
                    "severity": "error",
                    "message": calendar_error,
                    "ts": ts_ms,
                }
            )
        snapshot = {
            "ts": ts_ms,
            "version": self.config.version,
            "schema_version": self.config.schema_version,
            "pipeline_version": self.config.pipeline_version,
            "build_version": self.config.build_version,
            "process": {
                "pid": os.getpid(),
                "uptime_s": 0.0,
                "state": "running",
            },
            "market": self.calendar.market_state(ts_ms),
            "errors": errors,
            "degraded": degraded,
            "price": {
                "last_tick_ts_ms": 0,
                "last_snap_ts_ms": 0,
                "last_tick_event_ms": 0,
                "last_tick_snap_ms": 0,
                "tick_skew_ms": 0,
                "ticks_dropped_1m": 0,
                "tick_lag_ms": 0,
                "tick_total": 0,
                "tick_err_total": 0,
            },
            "fxcm": {
                "state": fxcm_state,
                "fsm_state": fxcm_state,
                "last_tick_ts_ms": 0,
                "last_ok_ts_ms": 0,
                "last_err": None,
                "last_err_ts_ms": 0,
                "reconnect_attempt": 0,
                "next_retry_ts_ms": 0,
                "stale_seconds": 0,
                "last_action": "",
                "ticks_total": 0,
                "stale_events_total": 0,
                "resubscribe_total": 0,
                "reconnect_total": 0,
                "publish_fail_total": 0,
                "contract_reject_total": 0,
            },
            "ohlcv_preview": {
                "last_publish_ts_ms": 0,
                "preview_total": 0,
                "preview_err_total": 0,
                "late_ticks_dropped_total": 0,
                "misaligned_open_time_total": 0,
                "past_mutations_total": 0,
                "last_bucket_open_ms": 0,
                "last_tick_ts_ms": 0,
                "last_late_tick": {
                    "tick_ts_ms": 0,
                    "bucket_open_ms": 0,
                    "current_bucket_open_ms": 0,
                },
                "last_bar_open_time_ms": {
                    "1m": 0,
                    "5m": 0,
                    "15m": 0,
                    "1h": 0,
                    "4h": 0,
                    "1d": 0,
                },
            },
            "ohlcv_final_1m": {
                "last_complete_bar_ms": 0,
                "lag_ms": 0,
                "bars_lookback_days": 0,
                "bars_total_est": 0,
            },
            "ohlcv_final": {
                "1m": {
                    "last_complete_bar_ms": 0,
                    "lag_ms": 0,
                    "bars_lookback_days": 0,
                    "bars_total_est": 0,
                },
                "15m": {
                    "last_complete_bar_ms": 0,
                    "lag_ms": 0,
                    "bars_lookback_days": 0,
                    "bars_total_est": 0,
                },
                "1h": {
                    "last_complete_bar_ms": 0,
                    "lag_ms": 0,
                    "bars_lookback_days": 0,
                    "bars_total_est": 0,
                },
                "4h": {
                    "last_complete_bar_ms": 0,
                    "lag_ms": 0,
                    "bars_lookback_days": 0,
                    "bars_total_est": 0,
                },
                "1d": {
                    "last_complete_bar_ms": 0,
                    "lag_ms": 0,
                    "bars_lookback_days": 0,
                    "bars_total_est": 0,
                },
            },
            "ohlcv": {
                "final_1m": {
                    "first_open_ms": None,
                    "last_close_ms": None,
                    "bars": 0,
                    "coverage_days": 0,
                    "retention_target_days": int(self.config.retention_target_days),
                    "coverage_ok": False,
                }
            },
            "history": {
                "ready": True,
                "not_ready_reason": "",
                "history_retry_after_ms": 0,
                "next_trading_open_ms": 0,
                "backoff_ms": 0,
                "backoff_active": False,
                "last_not_ready_ts_ms": 0,
            },
            "derived_rebuild": {
                "last_run_ts_ms": 0,
                "last_range_ms": [0, 0],
                "last_tfs": [],
                "state": "idle",
                "errors": [],
            },
            "no_mix": {
                "conflicts_total": 0,
                "last_conflict": None,
            },
            "tail_guard": {
                **_default_tail_guard_block(),
                "near": _default_tail_guard_block(),
                "far": _default_tail_guard_block(),
            },
            "republish": {
                "last_run_ts_ms": 0,
                "last_req_id": "",
                "skipped_by_watermark": False,
                "forced": False,
                "published_batches": 0,
                "state": "idle",
            },
            "reconcile": {
                "last_run_ts_ms": 0,
                "last_req_id": "",
                "last_end_ms": 0,
                "bucket_open_ms": 0,
                "bucket_close_ms": 0,
                "lookback_minutes": 0,
                "published_1m": 0,
                "skipped_1m": 0,
                "published_15m": 0,
                "skipped_15m": 0,
                "state": "idle",
                "last_error": None,
            },
            "bootstrap": {
                "state": "idle",
                "step": "",
                "last_step_ts_ms": 0,
                "steps": [],
                "last_error": None,
            },
            "command_bus": {
                "channel": self.config.ch_commands(),
                "state": command_bus_state,
                "last_heartbeat_ts_ms": 0,
                "last_error": command_bus_error,
            },
            "last_command": {
                "cmd": "bootstrap",
                "req_id": "bootstrap",
                "state": "ok",
                "started_ts": ts_ms,
                "finished_ts": ts_ms,
                "result": {},
            },
        }
        self._snapshot = snapshot
        return snapshot

    def record_history_state(
        self,
        ready: bool,
        not_ready_reason: str,
        history_retry_after_ms: int,
        next_trading_open_ms: int,
        backoff_ms: int,
        backoff_active: bool,
    ) -> None:
        history = self._snapshot.get("history")
        if not isinstance(history, dict):
            history = {
                "ready": True,
                "not_ready_reason": "",
                "history_retry_after_ms": 0,
                "next_trading_open_ms": 0,
                "backoff_ms": 0,
                "backoff_active": False,
                "last_not_ready_ts_ms": 0,
            }
        history["ready"] = bool(ready)
        history["not_ready_reason"] = str(not_ready_reason)
        history["history_retry_after_ms"] = int(history_retry_after_ms)
        history["next_trading_open_ms"] = int(next_trading_open_ms)
        history["backoff_ms"] = int(backoff_ms)
        history["backoff_active"] = bool(backoff_active)
        if not ready:
            history["last_not_ready_ts_ms"] = _now_ms()
        self._snapshot["history"] = history

    def snapshot(self) -> Dict[str, Any]:
        return dict(self._snapshot)

    def _update_process_fields(self, ts_ms: int) -> None:
        uptime_s = (ts_ms - self._started_ms) / 1000.0
        self._snapshot["ts"] = ts_ms
        self._snapshot["process"]["uptime_s"] = uptime_s
        self._snapshot["process"]["state"] = "running"
        self._snapshot["market"] = self.calendar.market_state(ts_ms, symbol=self._default_market_symbol())
        self._ensure_calendar_health(ts_ms)
        if self.metrics is not None:
            self.metrics.uptime_seconds.set(uptime_s)

    def _default_market_symbol(self) -> Optional[str]:
        symbols = self.config.fxcm_symbols
        if isinstance(symbols, list) and symbols:
            return str(symbols[0])
        symbol = str(self.config.preview_symbol) if self.config.preview_symbol else ""
        return symbol or None

    def append_error(
        self,
        code: str,
        severity: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        err = {
            "code": code,
            "severity": severity,
            "message": message,
            "ts": _now_ms(),
        }
        if context:
            err["context"] = context
        self._snapshot.setdefault("errors", []).append(err)
        if self.metrics is not None:
            self.metrics.errors_total.labels(code=code, severity=severity).inc()

    def append_public_error(
        self,
        code: str,
        severity: str,
        public_message: str,
        max_len: int = 160,
    ) -> None:
        message = _redact_public_message(public_message, max_len=max_len)
        self.append_error(code=code, severity=severity, message=message)

    def append_public_error_coalesced(
        self,
        code: str,
        severity: str,
        public_message: str,
        coalesce_key: Optional[str] = None,
        window_s: int = 30,
        max_len: int = 160,
    ) -> bool:
        key = str(coalesce_key or code)
        now_ms = _now_ms()
        window_ms = max(0, int(window_s) * 1000)
        with self._error_coalesce_lock:
            last_ts = int(self._error_coalesce_last_ts_by_key.get(key, 0))
            if window_ms > 0 and now_ms - last_ts < window_ms:
                self._bump_coalesce_error_count(code=code, now_ms=now_ms)
                return False
            self._error_coalesce_last_ts_by_key[key] = now_ms
        message = _redact_public_message(public_message, max_len=max_len)
        self.append_error(code=code, severity=severity, message=message)
        return True

    def _bump_coalesce_error_count(self, code: str, now_ms: int) -> None:
        errors = self._snapshot.get("errors")
        if not isinstance(errors, list) or not errors:
            return
        last = errors[-1]
        if not isinstance(last, dict) or last.get("code") != code:
            return
        context_obj = last.get("context")
        context: Dict[str, Any] = dict(context_obj) if isinstance(context_obj, dict) else {}
        prev_count = int(context.get("count", 1))
        context["count"] = prev_count + 1
        context["last_ts"] = now_ms
        last["context"] = context
        last["ts"] = now_ms
        errors[-1] = last
        self._snapshot["errors"] = errors

    def append_error_throttled(
        self,
        code: str,
        severity: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        throttle_key: Optional[str] = None,
        throttle_ms: int = 60_000,
        now_ms: Optional[int] = None,
        external_last_ts_by_key: Optional[Dict[str, int]] = None,
        external_lock: Optional[threading.Lock] = None,
    ) -> bool:
        key = str(throttle_key or code)
        now = int(now_ms or _now_ms())
        last_map = (
            external_last_ts_by_key if external_last_ts_by_key is not None else self._error_throttle_last_ts_by_key
        )
        lock = external_lock if external_lock is not None else self._error_throttle_lock
        with lock:
            last_ts = int(last_map.get(key, 0))
            if now - last_ts < int(throttle_ms):
                return False
            last_map[key] = now
        self.append_error(code=code, severity=severity, message=message, context=context)
        return True

    def mark_degraded(self, tag: str) -> None:
        degraded = self._snapshot.get("degraded")
        if not isinstance(degraded, list):
            degraded = []
        if tag not in degraded:
            degraded.append(tag)
        self._snapshot["degraded"] = degraded

    def clear_degraded(self, tag: str) -> None:
        degraded = self._snapshot.get("degraded")
        if not isinstance(degraded, list):
            return
        if tag in degraded:
            degraded.remove(tag)
        self._snapshot["degraded"] = degraded

    def _apply_soft_compact(self, payload_obj: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        if "tail_guard" not in payload_obj:
            return payload_obj, False
        soft_limit = int(self.config.status_soft_limit_bytes)
        detail_enabled = bool(self.config.status_tail_guard_detail_enabled)
        payload_size = status_payload_size_bytes(payload_obj)
        if detail_enabled and payload_size <= soft_limit:
            return payload_obj, False
        compact = dict(payload_obj)
        compact.pop("tail_guard", None)
        if detail_enabled and payload_size > soft_limit:
            degraded = compact.get("degraded")
            if not isinstance(degraded, list):
                degraded = []
            if "status_soft_compact_tail_guard" not in degraded:
                degraded.append("status_soft_compact_tail_guard")
            compact["degraded"] = _trim_list(degraded, STATUS_DEGRADED_MAX)
        return compact, True

    def is_preview_paused(self) -> bool:
        return bool(self._preview_paused)

    def _ensure_price(self) -> Dict[str, Any]:
        if "price" not in self._snapshot:
            self._snapshot["price"] = {
                "last_tick_ts_ms": 0,
                "last_snap_ts_ms": 0,
                "last_tick_event_ms": 0,
                "last_tick_snap_ms": 0,
                "tick_skew_ms": 0,
                "ticks_dropped_1m": 0,
                "tick_lag_ms": 0,
                "tick_total": 0,
                "tick_err_total": 0,
            }
        return dict(self._snapshot["price"])

    def _ensure_fxcm(self) -> Dict[str, Any]:
        if "fxcm" not in self._snapshot:
            self._snapshot["fxcm"] = {
                "state": "disabled",
                "fsm_state": "disabled",
                "last_tick_ts_ms": 0,
                "last_ok_ts_ms": 0,
                "last_err": None,
                "last_err_ts_ms": 0,
                "reconnect_attempt": 0,
                "next_retry_ts_ms": 0,
                "stale_seconds": 0,
                "last_action": "",
                "ticks_total": 0,
                "stale_events_total": 0,
                "resubscribe_total": 0,
                "reconnect_total": 0,
                "publish_fail_total": 0,
                "contract_reject_total": 0,
            }
        return dict(self._snapshot["fxcm"])

    def record_tick(self, tick_ts_ms: int, snap_ts_ms: int, now_ms: int) -> None:
        self._record_tick_window(now_ms=now_ms, seen_inc=1, dropped_inc=0)
        price = self._ensure_price()
        price["last_tick_ts_ms"] = tick_ts_ms
        price["last_snap_ts_ms"] = snap_ts_ms
        price["last_tick_event_ms"] = tick_ts_ms
        price["last_tick_snap_ms"] = snap_ts_ms
        skew_ms = int(snap_ts_ms) - int(tick_ts_ms)
        if skew_ms < 0:
            self.append_error(
                code="tick_skew_negative",
                severity="error",
                message="tick_skew_ms < 0",
                context={"tick_ts_ms": int(tick_ts_ms), "snap_ts_ms": int(snap_ts_ms)},
            )
            self.mark_degraded("tick_skew_negative")
            skew_ms = 0
        price["tick_skew_ms"] = skew_ms
        lag_ms = max(0, now_ms - snap_ts_ms)
        price["tick_lag_ms"] = lag_ms
        price["tick_total"] = int(price.get("tick_total", 0)) + 1
        self._snapshot["price"] = price
        if self.metrics is not None:
            self.metrics.ticks_total.inc()
            self.metrics.last_tick_ts_ms.set(tick_ts_ms)
            self.metrics.tick_lag_ms.set(lag_ms)
            self.metrics.fxcm_tick_skew_ms.set(skew_ms)

    def record_tick_error(self) -> None:
        price = self._ensure_price()
        price["tick_total"] = int(price.get("tick_total", 0)) + 1
        price["tick_err_total"] = int(price.get("tick_err_total", 0)) + 1
        self._snapshot["price"] = price
        if self.metrics is not None:
            self.metrics.tick_errors_total.inc()

    def record_tick_drop_missing_event(self, now_ms: int) -> None:
        self._record_tick_window(now_ms=now_ms, seen_inc=1, dropped_inc=1)
        price = self._ensure_price()
        bucket_ms = int(now_ms) - (int(now_ms) % 60_000)
        if self._tick_drop_bucket_ms != bucket_ms:
            self._tick_drop_bucket_ms = bucket_ms
            price["ticks_dropped_1m"] = 0
        price["ticks_dropped_1m"] = int(price.get("ticks_dropped_1m", 0)) + 1
        self._snapshot["price"] = price

    def _record_tick_window(self, now_ms: int, seen_inc: int, dropped_inc: int) -> None:
        ts_ms = int(now_ms)
        self._tick_window.append((ts_ms, int(seen_inc), int(dropped_inc)))
        self._tick_window_seen_total += int(seen_inc)
        self._tick_window_dropped_total += int(dropped_inc)
        self._prune_tick_window(now_ms=ts_ms)
        self._update_tick_event_health()

    def _prune_tick_window(self, now_ms: int) -> None:
        cutoff = int(now_ms) - int(self._tick_window_ms)
        while self._tick_window and self._tick_window[0][0] < cutoff:
            ts_ms, seen_inc, dropped_inc = self._tick_window.popleft()
            _ = ts_ms
            self._tick_window_seen_total -= int(seen_inc)
            self._tick_window_dropped_total -= int(dropped_inc)
        if self._tick_window_seen_total < 0:
            self._tick_window_seen_total = 0
        if self._tick_window_dropped_total < 0:
            self._tick_window_dropped_total = 0

    def _update_tick_event_health(self) -> None:
        if self._tick_window_seen_total <= 0:
            return
        drop_rate = float(self._tick_window_dropped_total) / float(self._tick_window_seen_total)
        if drop_rate >= 0.5:
            self.mark_degraded("tick_event_time_unavailable")
            self._preview_paused = True
            return
        if drop_rate <= 0.1:
            self.clear_degraded("tick_event_time_unavailable")
            self._preview_paused = False

    def record_tick_contract_reject(self) -> None:
        price = self._ensure_price()
        price["tick_err_total"] = int(price.get("tick_err_total", 0)) + 1
        self._snapshot["price"] = price
        if self.metrics is not None:
            self.metrics.tick_contract_reject_total.inc()

    def update_fxcm_state(
        self,
        state: str,
        last_tick_ts_ms: int,
        last_err: Optional[str],
        last_ok_ts_ms: Optional[int] = None,
        last_err_ts_ms: Optional[int] = None,
        reconnect_attempt: Optional[int] = None,
        next_retry_ts_ms: Optional[int] = None,
        fsm_state: Optional[str] = None,
        stale_seconds: Optional[int] = None,
        last_action: Optional[str] = None,
    ) -> None:
        fxcm = self._ensure_fxcm()
        fxcm["state"] = state
        fxcm["last_tick_ts_ms"] = int(last_tick_ts_ms)
        fxcm["last_err"] = last_err
        if last_ok_ts_ms is not None:
            fxcm["last_ok_ts_ms"] = int(last_ok_ts_ms)
        if last_err_ts_ms is not None:
            fxcm["last_err_ts_ms"] = int(last_err_ts_ms)
        if reconnect_attempt is not None:
            fxcm["reconnect_attempt"] = int(reconnect_attempt)
        if next_retry_ts_ms is not None:
            fxcm["next_retry_ts_ms"] = int(next_retry_ts_ms)
        if fsm_state is not None:
            fxcm["fsm_state"] = str(fsm_state)
        else:
            fxcm["fsm_state"] = str(state)
        if stale_seconds is not None:
            fxcm["stale_seconds"] = int(stale_seconds)
        if last_action is not None:
            fxcm["last_action"] = str(last_action)
        self._snapshot["fxcm"] = fxcm

    def record_fxcm_tick(self, tick_ts_ms: int) -> None:
        fxcm = self._ensure_fxcm()
        fxcm["last_tick_ts_ms"] = int(tick_ts_ms)
        if fxcm.get("state") in {"connected", "connecting"}:
            fxcm["state"] = "subscribed_offers"
        self._snapshot["fxcm"] = fxcm

    def update_fxcm_fsm(
        self,
        fsm_state: str,
        last_tick_ts_ms: int,
        stale_seconds: int,
        last_action: str,
    ) -> None:
        fxcm = self._ensure_fxcm()
        fxcm["fsm_state"] = str(fsm_state)
        fxcm["state"] = str(fsm_state)
        fxcm["last_tick_ts_ms"] = int(last_tick_ts_ms)
        fxcm["stale_seconds"] = int(stale_seconds)
        fxcm["last_action"] = str(last_action)
        self._snapshot["fxcm"] = fxcm

    def record_fxcm_tick_total(self, tick_ts_ms: int) -> None:
        fxcm = self._ensure_fxcm()
        fxcm["ticks_total"] = int(fxcm.get("ticks_total", 0)) + 1
        fxcm["last_tick_ts_ms"] = int(tick_ts_ms)
        self._snapshot["fxcm"] = fxcm
        if self.metrics is not None:
            self.metrics.fxcm_ticks_total.inc()
            self.metrics.fxcm_last_tick_ts_ms.set(int(tick_ts_ms))

    def record_fxcm_stale_event(self) -> None:
        fxcm = self._ensure_fxcm()
        fxcm["stale_events_total"] = int(fxcm.get("stale_events_total", 0)) + 1
        self._snapshot["fxcm"] = fxcm
        if self.metrics is not None:
            self.metrics.fxcm_stale_events_total.inc()

    def record_fxcm_resubscribe(self) -> None:
        fxcm = self._ensure_fxcm()
        fxcm["resubscribe_total"] = int(fxcm.get("resubscribe_total", 0)) + 1
        self._snapshot["fxcm"] = fxcm
        if self.metrics is not None:
            self.metrics.fxcm_resubscribe_total.inc()

    def record_fxcm_reconnect(self) -> None:
        fxcm = self._ensure_fxcm()
        fxcm["reconnect_total"] = int(fxcm.get("reconnect_total", 0)) + 1
        self._snapshot["fxcm"] = fxcm
        if self.metrics is not None:
            self.metrics.fxcm_reconnect_total.inc()

    def record_fxcm_publish_fail(self) -> None:
        fxcm = self._ensure_fxcm()
        fxcm["publish_fail_total"] = int(fxcm.get("publish_fail_total", 0)) + 1
        self._snapshot["fxcm"] = fxcm
        if self.metrics is not None:
            self.metrics.fxcm_publish_fail_total.inc()

    def record_fxcm_contract_reject(self) -> None:
        fxcm = self._ensure_fxcm()
        fxcm["contract_reject_total"] = int(fxcm.get("contract_reject_total", 0)) + 1
        self._snapshot["fxcm"] = fxcm
        if self.metrics is not None:
            self.metrics.fxcm_contract_reject_total.inc()

    def record_ohlcv_publish(self, tf: str, bar_open_time_ms: int, publish_ts_ms: int) -> None:
        preview = self._snapshot.get("ohlcv_preview")
        if not isinstance(preview, dict):
            preview = {
                "last_publish_ts_ms": 0,
                "preview_total": 0,
                "preview_err_total": 0,
                "late_ticks_dropped_total": 0,
                "misaligned_open_time_total": 0,
                "past_mutations_total": 0,
                "last_bucket_open_ms": 0,
                "last_tick_ts_ms": 0,
                "last_late_tick": {
                    "tick_ts_ms": 0,
                    "bucket_open_ms": 0,
                    "current_bucket_open_ms": 0,
                },
                "last_bar_open_time_ms": {
                    "1m": 0,
                    "5m": 0,
                    "15m": 0,
                    "1h": 0,
                    "4h": 0,
                    "1d": 0,
                },
            }
        preview["last_publish_ts_ms"] = publish_ts_ms
        preview["preview_total"] = int(preview.get("preview_total", 0)) + 1
        last_map = preview.get("last_bar_open_time_ms", {})
        if isinstance(last_map, dict):
            last_map[tf] = bar_open_time_ms
        preview["last_bar_open_time_ms"] = last_map
        self._snapshot["ohlcv_preview"] = preview
        if self.metrics is not None:
            self.metrics.ohlcv_preview_total.inc()
            self.metrics.ohlcv_preview_batches_total.inc()
            self.metrics.ohlcv_preview_last_publish_ts_ms.set(publish_ts_ms)

    def record_ohlcv_error(self) -> None:
        preview = self._snapshot.get("ohlcv_preview")
        if not isinstance(preview, dict):
            preview = {
                "last_publish_ts_ms": 0,
                "preview_total": 0,
                "preview_err_total": 0,
                "late_ticks_dropped_total": 0,
                "misaligned_open_time_total": 0,
                "past_mutations_total": 0,
                "last_bucket_open_ms": 0,
                "last_tick_ts_ms": 0,
                "last_late_tick": {
                    "tick_ts_ms": 0,
                    "bucket_open_ms": 0,
                    "current_bucket_open_ms": 0,
                },
                "last_bar_open_time_ms": {
                    "1m": 0,
                    "5m": 0,
                    "15m": 0,
                    "1h": 0,
                    "4h": 0,
                    "1d": 0,
                },
            }
        preview["preview_err_total"] = int(preview.get("preview_err_total", 0)) + 1
        self._snapshot["ohlcv_preview"] = preview
        if self.metrics is not None:
            self.metrics.ohlcv_preview_errors_total.inc()
            self.metrics.ohlcv_preview_validation_errors_total.inc()

    def record_ohlcv_preview_rail(
        self,
        tf: str,
        last_tick_ts_ms: int,
        last_bucket_open_ms: int,
        late_ticks_dropped_total: int,
        misaligned_open_time_total: int,
        past_mutations_total: int,
        last_late_tick: Dict[str, Any],
    ) -> None:
        preview = self._snapshot.get("ohlcv_preview")
        if not isinstance(preview, dict):
            preview = {
                "last_publish_ts_ms": 0,
                "preview_total": 0,
                "preview_err_total": 0,
                "late_ticks_dropped_total": 0,
                "misaligned_open_time_total": 0,
                "past_mutations_total": 0,
                "last_bucket_open_ms": 0,
                "last_tick_ts_ms": 0,
                "last_late_tick": {
                    "tick_ts_ms": 0,
                    "bucket_open_ms": 0,
                    "current_bucket_open_ms": 0,
                },
                "last_bar_open_time_ms": {
                    "1m": 0,
                    "5m": 0,
                    "15m": 0,
                    "1h": 0,
                    "4h": 0,
                    "1d": 0,
                },
            }
        prev_late_total = int(preview.get("late_ticks_dropped_total", 0))
        preview["last_tick_ts_ms"] = int(last_tick_ts_ms)
        preview["last_bucket_open_ms"] = int(last_bucket_open_ms)
        preview["late_ticks_dropped_total"] = int(late_ticks_dropped_total)
        preview["misaligned_open_time_total"] = int(misaligned_open_time_total)
        preview["past_mutations_total"] = int(past_mutations_total)
        if isinstance(last_late_tick, dict):
            preview["last_late_tick"] = {
                "tick_ts_ms": int(last_late_tick.get("tick_ts_ms", 0)),
                "bucket_open_ms": int(last_late_tick.get("bucket_open_ms", 0)),
                "current_bucket_open_ms": int(last_late_tick.get("current_bucket_open_ms", 0)),
            }
        if isinstance(tf, str) and tf in preview.get("last_bar_open_time_ms", {}):
            preview["last_bar_open_time_ms"][tf] = int(preview.get("last_bar_open_time_ms", {}).get(tf, 0))
        self._snapshot["ohlcv_preview"] = preview
        if self.metrics is not None:
            delta = int(late_ticks_dropped_total) - prev_late_total
            if delta > 0:
                self.metrics.ohlcv_preview_late_ticks_dropped_total.labels(tf=str(tf)).inc(delta)

    def record_final_publish(
        self,
        last_complete_bar_ms: int,
        now_ms: int,
        lookback_days: int,
        tf: str = "1m",
        bars_total_est: Optional[int] = None,
    ) -> None:
        if tf == "1m" and last_complete_bar_ms % 60_000 != 59_999:
            raise ValueError("last_complete_bar_ms має бути close_time (…9999) для 1m final")
        final = self._snapshot.get("ohlcv_final_1m")
        if tf == "1m":
            if not isinstance(final, dict):
                final = {
                    "last_complete_bar_ms": 0,
                    "lag_ms": 0,
                    "bars_lookback_days": 0,
                    "bars_total_est": 0,
                }
            final["last_complete_bar_ms"] = last_complete_bar_ms
            final["lag_ms"] = max(0, now_ms - last_complete_bar_ms)
            final["bars_lookback_days"] = int(lookback_days)
            if bars_total_est is None:
                final["bars_total_est"] = int(lookback_days) * 24 * 60
            else:
                final["bars_total_est"] = int(bars_total_est)
            self._snapshot["ohlcv_final_1m"] = final

        self._record_final_map(tf, last_complete_bar_ms, now_ms, lookback_days, bars_total_est)
        if tf == "1m":
            self._mirror_final_1m()

    def _record_final_map(
        self,
        tf: str,
        last_complete_bar_ms: int,
        now_ms: int,
        lookback_days: int,
        bars_total_est: Optional[int],
    ) -> None:
        final_map = self._snapshot.get("ohlcv_final")
        if not isinstance(final_map, dict):
            final_map = {}
        entry = final_map.get(tf)
        if not isinstance(entry, dict):
            entry = {
                "last_complete_bar_ms": 0,
                "lag_ms": 0,
                "bars_lookback_days": 0,
                "bars_total_est": 0,
            }
        entry["last_complete_bar_ms"] = last_complete_bar_ms
        entry["lag_ms"] = max(0, now_ms - last_complete_bar_ms)
        entry["bars_lookback_days"] = int(lookback_days)
        if tf == "1m":
            if bars_total_est is None:
                final_1m = self._snapshot.get("ohlcv_final_1m")
                if isinstance(final_1m, dict) and "bars_total_est" in final_1m:
                    entry["bars_total_est"] = int(final_1m.get("bars_total_est", 0))
                else:
                    entry["bars_total_est"] = int(lookback_days) * 24 * 60
            else:
                entry["bars_total_est"] = int(bars_total_est)
        else:
            entry["bars_total_est"] = int(lookback_days) * 24 * 60
        final_map[tf] = entry
        self._snapshot["ohlcv_final"] = final_map

    def _mirror_final_1m(self) -> None:
        final_map = self._snapshot.get("ohlcv_final")
        if not isinstance(final_map, dict):
            return
        entry = final_map.get("1m")
        if isinstance(entry, dict):
            self._snapshot["ohlcv_final_1m"] = dict(entry)

    def record_final_1m_coverage(
        self,
        first_open_ms: Optional[int],
        last_close_ms: Optional[int],
        bars: int,
        coverage_days: int,
        retention_target_days: int,
    ) -> None:
        ohlcv = self._snapshot.get("ohlcv")
        if not isinstance(ohlcv, dict):
            ohlcv = {}
        final_1m = ohlcv.get("final_1m")
        if not isinstance(final_1m, dict):
            final_1m = {}
        final_1m["first_open_ms"] = int(first_open_ms) if first_open_ms is not None else None
        final_1m["last_close_ms"] = int(last_close_ms) if last_close_ms is not None else None
        final_1m["bars"] = int(bars)
        final_1m["coverage_days"] = max(0, int(coverage_days))
        final_1m["retention_target_days"] = max(0, int(retention_target_days))
        final_1m["coverage_ok"] = bool(coverage_days >= retention_target_days and bars > 0)
        ohlcv["final_1m"] = final_1m
        self._snapshot["ohlcv"] = ohlcv

    def record_derived_rebuild(
        self,
        state: str,
        start_ms: int,
        end_ms: int,
        tfs: List[str],
        last_error: Optional[str],
    ) -> None:
        derived = self._snapshot.get("derived_rebuild")
        if not isinstance(derived, dict):
            derived = {
                "last_run_ts_ms": 0,
                "last_range_ms": [0, 0],
                "last_tfs": [],
                "state": "idle",
                "errors": [],
            }
        derived["last_run_ts_ms"] = _now_ms()
        derived["last_range_ms"] = [int(start_ms), int(end_ms)]
        derived["last_tfs"] = list(tfs)
        derived["state"] = state
        if last_error:
            derived.setdefault("errors", []).append(last_error)
        self._snapshot["derived_rebuild"] = derived

    def record_no_mix_conflict(self, symbol: str, tf: str, message: str) -> None:
        no_mix = self._snapshot.get("no_mix")
        if not isinstance(no_mix, dict):
            no_mix = {"conflicts_total": 0, "last_conflict": None}
        no_mix["conflicts_total"] = int(no_mix.get("conflicts_total", 0)) + 1
        no_mix["last_conflict"] = {
            "symbol": symbol,
            "tf": tf,
            "message": message,
            "ts": _now_ms(),
        }
        self._snapshot["no_mix"] = no_mix

    def record_tail_guard_tf(self, tf: str, state: Any, window_hours: int, tier: str = "far") -> None:
        tail = self._ensure_tail_guard_tiers()
        block = tail.get("near") if tier == "near" else tail.get("far")
        if not isinstance(block, dict):
            block = _default_tail_guard_block()
        tf_states = block.get("tf_states")
        if not isinstance(tf_states, dict):
            tf_states = {}
        tf_states[tf] = {
            "missing_bars": int(state.missing_bars),
            "skipped_by_ttl": bool(state.skipped_by_ttl),
            "state": str(state.status),
        }
        block["tf_states"] = tf_states
        block["window_hours"] = window_hours
        block["last_audit_ts_ms"] = _now_ms()
        if tier == "near":
            tail["near"] = block
        else:
            tail["far"] = block
            self._sync_tail_guard_from_block(tail, block)
        self._snapshot["tail_guard"] = tail

    def record_tail_guard_mark(self, tf: str, mark: Dict[str, Any], tier: str = "far") -> None:
        tail = self._ensure_tail_guard_tiers()
        block = tail.get("near") if tier == "near" else tail.get("far")
        if not isinstance(block, dict):
            block = _default_tail_guard_block()
        marks = block.get("marks")
        if not isinstance(marks, dict):
            marks = {}
        marks[tf] = {
            "verified_from_ms": int(mark.get("verified_from_ms", 0)),
            "verified_until_ms": int(mark.get("verified_until_ms", 0)),
            "checked_until_close_ms": int(mark.get("checked_until_close_ms", 0)),
            "etag_last_complete_bar_ms": int(mark.get("etag_last_complete_bar_ms", 0)),
            "last_audit_ts_ms": int(mark.get("last_audit_ts_ms", 0)),
        }
        block["marks"] = marks
        if tier == "near":
            tail["near"] = block
        else:
            tail["far"] = block
            self._sync_tail_guard_from_block(tail, block)
        self._snapshot["tail_guard"] = tail

    def record_tail_guard_summary(
        self,
        window_hours: int,
        tf_states: Dict[str, Any],
        repaired: bool,
        tier: str = "far",
    ) -> None:
        tail = self._ensure_tail_guard_tiers()
        block = tail.get("near") if tier == "near" else tail.get("far")
        if not isinstance(block, dict):
            block = _default_tail_guard_block()
        required_tfs = ["1m", "15m", "1h", "4h", "1d"]
        mapped = {}
        for tf in required_tfs:
            state = tf_states.get(tf)
            if state is None:
                mapped[tf] = {
                    "missing_bars": 0,
                    "skipped_by_ttl": False,
                    "state": "idle",
                }
                continue
            mapped[tf] = {
                "missing_bars": int(state.missing_bars),
                "skipped_by_ttl": bool(state.skipped_by_ttl),
                "state": str(state.status),
            }
        block["tf_states"] = mapped
        block["window_hours"] = int(window_hours)
        block["last_audit_ts_ms"] = _now_ms()
        block["repaired"] = bool(repaired)
        if tier == "near":
            tail["near"] = block
        else:
            tail["far"] = block
            self._sync_tail_guard_from_block(tail, block)
        self._snapshot["tail_guard"] = tail

    def record_republish(
        self,
        req_id: str,
        skipped_by_watermark: bool,
        forced: bool,
        published_batches: int,
        state: str,
    ) -> None:
        republish = self._snapshot.get("republish")
        if not isinstance(republish, dict):
            republish = {
                "last_run_ts_ms": 0,
                "last_req_id": "",
                "skipped_by_watermark": False,
                "forced": False,
                "published_batches": 0,
                "state": "idle",
            }
        republish["last_run_ts_ms"] = _now_ms()
        republish["last_req_id"] = req_id
        republish["skipped_by_watermark"] = bool(skipped_by_watermark)
        republish["forced"] = bool(forced)
        republish["published_batches"] = int(published_batches)
        republish["state"] = state
        self._snapshot["republish"] = republish

    def record_reconcile(
        self,
        req_id: str,
        bucket_open_ms: int,
        bucket_close_ms: int,
        lookback_minutes: int,
        published_1m: int,
        skipped_1m: int,
        published_15m: int,
        skipped_15m: int,
        state: str,
        error: Optional[Dict[str, Any]] = None,
    ) -> None:
        reconcile = self._snapshot.get("reconcile")
        if not isinstance(reconcile, dict):
            reconcile = {
                "last_run_ts_ms": 0,
                "last_req_id": "",
                "last_end_ms": 0,
                "bucket_open_ms": 0,
                "bucket_close_ms": 0,
                "lookback_minutes": 0,
                "published_1m": 0,
                "skipped_1m": 0,
                "published_15m": 0,
                "skipped_15m": 0,
                "state": "idle",
                "last_error": None,
            }
        reconcile["last_run_ts_ms"] = _now_ms()
        reconcile["last_req_id"] = str(req_id)
        if "last_end_ms" not in reconcile:
            reconcile["last_end_ms"] = 0
        reconcile["bucket_open_ms"] = int(bucket_open_ms)
        reconcile["bucket_close_ms"] = int(bucket_close_ms)
        reconcile["lookback_minutes"] = int(lookback_minutes)
        reconcile["published_1m"] = int(published_1m)
        reconcile["skipped_1m"] = int(skipped_1m)
        reconcile["published_15m"] = int(published_15m)
        reconcile["skipped_15m"] = int(skipped_15m)
        reconcile["state"] = str(state)
        if error is None:
            reconcile["last_error"] = None
        else:
            err_obj = dict(error)
            reconcile["last_error"] = err_obj
            code = str(err_obj.get("code") or "reconcile_error")
            message = str(err_obj.get("message") or "reconcile error")
            self.append_error(
                code=code,
                severity="error",
                message=message,
                context={"scope": "reconcile"},
            )
            self.mark_degraded(code)
        self._snapshot["reconcile"] = reconcile

    def get_reconcile_last_end_ms(self) -> int:
        reconcile = self._snapshot.get("reconcile")
        if not isinstance(reconcile, dict):
            return 0
        return int(reconcile.get("last_end_ms", 0))

    def record_reconcile_trigger(self, end_ms: int) -> None:
        reconcile = self._snapshot.get("reconcile")
        if not isinstance(reconcile, dict):
            reconcile = {
                "last_run_ts_ms": 0,
                "last_req_id": "",
                "last_end_ms": 0,
                "bucket_open_ms": 0,
                "bucket_close_ms": 0,
                "lookback_minutes": 0,
                "published_1m": 0,
                "skipped_1m": 0,
                "published_15m": 0,
                "skipped_15m": 0,
                "state": "idle",
                "last_error": None,
            }
        reconcile["last_end_ms"] = int(end_ms)
        self._snapshot["reconcile"] = reconcile

    def record_bootstrap_step(
        self,
        step: str,
        state: str,
        error: Optional[Dict[str, Any]] = None,
    ) -> None:
        bootstrap = self._snapshot.get("bootstrap")
        if not isinstance(bootstrap, dict):
            bootstrap = {
                "state": "idle",
                "step": "",
                "last_step_ts_ms": 0,
                "steps": [],
                "last_error": None,
            }
        bootstrap["state"] = str(state)
        bootstrap["step"] = str(step)
        bootstrap["last_step_ts_ms"] = _now_ms()
        steps = bootstrap.get("steps")
        if not isinstance(steps, list):
            steps = []
        steps.append({"step": str(step), "state": str(state), "ts": int(bootstrap["last_step_ts_ms"])})
        bootstrap["steps"] = steps
        if error is None:
            bootstrap["last_error"] = None
        else:
            err_obj = dict(error)
            bootstrap["last_error"] = err_obj
            code = str(err_obj.get("code") or "bootstrap_error")
            message = str(err_obj.get("message") or "bootstrap error")
            self.append_error(
                code=code,
                severity="error",
                message=message,
                context={"step": str(step)},
            )
            self.mark_degraded(code)
        self._snapshot["bootstrap"] = bootstrap

    def update_command_bus_heartbeat(self, channel: str, ts_ms: Optional[int] = None) -> None:
        command_bus = self._snapshot.get("command_bus")
        if not isinstance(command_bus, dict):
            command_bus = {
                "channel": channel,
                "state": "running",
                "last_heartbeat_ts_ms": 0,
                "last_error": None,
            }
        ts = _now_ms() if ts_ms is None else int(ts_ms)
        command_bus["channel"] = channel
        command_bus["state"] = "running"
        command_bus["last_heartbeat_ts_ms"] = ts
        command_bus["last_error"] = None
        self._snapshot["command_bus"] = command_bus

    def update_command_bus_error(self, channel: str, code: str, message: str, ts_ms: Optional[int] = None) -> None:
        command_bus = self._snapshot.get("command_bus")
        if not isinstance(command_bus, dict):
            command_bus = {
                "channel": channel,
                "state": "error",
                "last_heartbeat_ts_ms": 0,
                "last_error": None,
            }
        ts = _now_ms() if ts_ms is None else int(ts_ms)
        command_bus["channel"] = channel
        command_bus["state"] = "error"
        command_bus["last_error"] = {
            "code": code,
            "message": message,
            "ts": ts,
        }
        self._snapshot["command_bus"] = command_bus

    def set_last_command_running(self, cmd: str, req_id: str, started_ts: int) -> None:
        self._snapshot["last_command"] = {
            "cmd": cmd,
            "req_id": req_id,
            "state": "running",
            "started_ts": started_ts,
        }

    def set_last_command_ok(
        self,
        cmd: str,
        req_id: str,
        started_ts: int,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        now_ms = _now_ms()
        if result is None:
            existing = self._snapshot.get("last_command")
            if isinstance(existing, dict) and isinstance(existing.get("result"), dict):
                result = dict(existing.get("result", {}))
        self._snapshot["last_command"] = {
            "cmd": cmd,
            "req_id": req_id,
            "state": "ok",
            "started_ts": started_ts,
            "finished_ts": now_ms,
            "result": result or {},
        }

    def set_last_command_error(
        self,
        cmd: str,
        req_id: str,
        started_ts: int,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        now_ms = _now_ms()
        if result is None:
            existing = self._snapshot.get("last_command")
            if isinstance(existing, dict) and isinstance(existing.get("result"), dict):
                result = dict(existing.get("result", {}))
        self._snapshot["last_command"] = {
            "cmd": cmd,
            "req_id": req_id,
            "state": "error",
            "started_ts": started_ts,
            "finished_ts": now_ms,
            "result": result or {},
        }

    def update_last_command_result(self, result: Dict[str, Any]) -> None:
        last = self._snapshot.get("last_command")
        if not isinstance(last, dict):
            return
        last["result"] = dict(result)
        self._snapshot["last_command"] = last

    def publish_snapshot(self) -> None:
        ts_ms = _now_ms()
        self._update_process_fields(ts_ms)
        self._mirror_final_1m()
        payload_obj = build_status_pubsub_payload(self._snapshot)
        payload_obj, _ = self._apply_soft_compact(payload_obj)
        self.validator.validate_status_v2(payload_obj)
        payload = json.dumps(payload_obj, ensure_ascii=False, separators=(",", ":"))
        payload_size = len(payload.encode("utf-8"))
        if payload_size > STATUS_PUBSUB_MAX_BYTES:
            errors = self._snapshot.get("errors")
            if isinstance(errors, list) and errors:
                last = errors[-1]
                if isinstance(last, dict) and last.get("code") == "status_payload_too_large":
                    context_obj = last.get("context")
                    context: Dict[str, Any] = dict(context_obj) if isinstance(context_obj, dict) else {}
                    prev_count = int(context.get("count", 1))
                    context["size_bytes"] = payload_size
                    context["count"] = prev_count + 1
                    last["context"] = context
                    last["ts"] = _now_ms()
                    errors[-1] = last
                    self._snapshot["errors"] = errors
                else:
                    self.append_error(
                        code="status_payload_too_large",
                        severity="error",
                        message="Payload status pubsub перевищує 8KB",
                        context={"size_bytes": payload_size},
                    )
            else:
                self.append_error(
                    code="status_payload_too_large",
                    severity="error",
                    message="Payload status pubsub перевищує 8KB",
                    context={"size_bytes": payload_size},
                )
            if self.metrics is not None:
                self.metrics.status_payload_too_large_total.inc()
            compact_after_error = build_status_pubsub_payload(self._snapshot)

            def _payload_size_bytes(obj: Dict[str, Any]) -> int:
                data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
                return len(data.encode("utf-8"))

            compact_obj = dict(compact_after_error)
            compact_size = _payload_size_bytes(compact_obj)
            if compact_size > STATUS_PUBSUB_MAX_BYTES:
                compact_obj.pop("tail_guard", None)
                compact_size = _payload_size_bytes(compact_obj)
            if compact_size > STATUS_PUBSUB_MAX_BYTES:
                compact_obj.pop("ohlcv_final", None)
                compact_obj.pop("ohlcv_final_1m", None)
                compact_size = _payload_size_bytes(compact_obj)
            if compact_size > STATUS_PUBSUB_MAX_BYTES:
                errors = compact_obj.get("errors")
                if isinstance(errors, list):
                    deduped: List[Dict[str, Any]] = []
                    seen_codes: set = set()
                    for entry in errors:
                        if not isinstance(entry, dict):
                            continue
                        code = entry.get("code")
                        if not code or code in seen_codes:
                            continue
                        seen_codes.add(code)
                        deduped.append(entry)
                        if len(deduped) >= 5:
                            break
                    compact_obj["errors"] = deduped
            self.validator.validate_status_v2(compact_obj)
            compact_json = json.dumps(compact_obj, ensure_ascii=False, separators=(",", ":"))
            self.publisher.set_snapshot(self.config.key_status_snapshot(), compact_json)
            self.publisher.publish(self.config.ch_status(), compact_json)
            self._last_publish_ms = ts_ms
            if self.metrics is not None:
                self.metrics.last_status_ts_ms.set(ts_ms)
            return
        self.publisher.set_snapshot(self.config.key_status_snapshot(), payload)
        self.publisher.publish(self.config.ch_status(), payload)
        self._last_publish_ms = ts_ms
        if self.metrics is not None:
            self.metrics.last_status_ts_ms.set(ts_ms)

    def publish_if_due(self, interval_ms: int) -> None:
        now_ms = _now_ms()
        if now_ms - self._last_publish_ms >= interval_ms:
            self.publish_snapshot()
