from __future__ import annotations

from pathlib import Path

import pytest

from core.validation.validator import ContractError, SchemaValidator


def _valid_status() -> dict:
    return {
        "ts": 1,
        "version": "0.0.0",
        "schema_version": 2,
        "pipeline_version": "p0",
        "build_version": "dev",
        "process": {"pid": 1, "uptime_s": 0.0, "state": "running"},
        "market": {
            "is_open": True,
            "next_open_utc": "2026-01-01T00:00:00Z",
            "next_pause_utc": "2026-01-01T00:00:00Z",
            "calendar_tag": "fxcm_calendar_v1_ny",
            "tz_backend": "zoneinfo",
        },
        "errors": [],
        "degraded": [],
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
        "command_bus": {
            "channel": "fxcm_local:commands",
            "state": "running",
            "last_heartbeat_ts_ms": 1,
            "last_error": None,
        },
        "last_command": {
            "cmd": "bootstrap",
            "req_id": "bootstrap",
            "state": "ok",
            "started_ts": 1,
            "finished_ts": 1,
            "result": {},
        },
        "fxcm": {
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
            "1m": {"last_complete_bar_ms": 0, "lag_ms": 0, "bars_lookback_days": 0, "bars_total_est": 0},
            "15m": {"last_complete_bar_ms": 0, "lag_ms": 0, "bars_lookback_days": 0, "bars_total_est": 0},
            "1h": {"last_complete_bar_ms": 0, "lag_ms": 0, "bars_lookback_days": 0, "bars_total_est": 0},
            "4h": {"last_complete_bar_ms": 0, "lag_ms": 0, "bars_lookback_days": 0, "bars_total_est": 0},
            "1d": {"last_complete_bar_ms": 0, "lag_ms": 0, "bars_lookback_days": 0, "bars_total_est": 0},
        },
        "ohlcv": {
            "final_1m": {
                "first_open_ms": None,
                "last_close_ms": None,
                "bars": 0,
                "coverage_days": 0,
                "retention_target_days": 365,
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
        },
        "republish": {
            "last_run_ts_ms": 0,
            "last_req_id": "",
            "skipped_by_watermark": False,
            "forced": False,
            "published_batches": 0,
            "state": "idle",
        },
    }


def test_status_v2_valid() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    validator.validate_status_v2(_valid_status())


def test_status_v2_extra_field_rejected() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    payload = _valid_status()
    payload["extra"] = "nope"
    with pytest.raises(ContractError):
        validator.validate_status_v2(payload)
