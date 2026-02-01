from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional, cast

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.status import StatusManager


class DummyPublisher:
    def __init__(self) -> None:
        self.snapshot_json: Optional[str] = None
        self.publish_json: Optional[str] = None

    def set_snapshot(self, key: str, json_str: str) -> None:
        self.snapshot_json = json_str

    def publish(self, channel: str, json_str: str) -> None:
        self.publish_json = json_str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _tail_guard_block() -> Dict[str, Any]:
    tf_states = {
        "1m": {"missing_bars": 12, "skipped_by_ttl": False, "state": "gap"},
        "15m": {"missing_bars": 3, "skipped_by_ttl": False, "state": "ok"},
        "1h": {"missing_bars": 1, "skipped_by_ttl": True, "state": "ok"},
        "4h": {"missing_bars": 0, "skipped_by_ttl": False, "state": "idle"},
        "1d": {"missing_bars": 0, "skipped_by_ttl": False, "state": "idle"},
    }
    marks = {
        "1m": {
            "verified_from_ms": 1700000000000,
            "verified_until_ms": 1700003600000,
            "checked_until_close_ms": 1700003599999,
            "etag_last_complete_bar_ms": 1700003599999,
            "last_audit_ts_ms": 1700003600123,
        },
        "15m": {
            "verified_from_ms": 1700000000000,
            "verified_until_ms": 1700003600000,
            "checked_until_close_ms": 1700003599999,
            "etag_last_complete_bar_ms": 1700003599999,
            "last_audit_ts_ms": 1700003600123,
        },
        "1h": {
            "verified_from_ms": 1700000000000,
            "verified_until_ms": 1700003600000,
            "checked_until_close_ms": 1700003599999,
            "etag_last_complete_bar_ms": 1700003599999,
            "last_audit_ts_ms": 1700003600123,
        },
        "4h": {
            "verified_from_ms": 1700000000000,
            "verified_until_ms": 1700003600000,
            "checked_until_close_ms": 1700003599999,
            "etag_last_complete_bar_ms": 1700003599999,
            "last_audit_ts_ms": 1700003600123,
        },
        "1d": {
            "verified_from_ms": 1700000000000,
            "verified_until_ms": 1700003600000,
            "checked_until_close_ms": 1700003599999,
            "etag_last_complete_bar_ms": 1700003599999,
            "last_audit_ts_ms": 1700003600123,
        },
    }
    return {
        "last_audit_ts_ms": 1700003600123,
        "window_hours": 48,
        "tf_states": tf_states,
        "marks": marks,
        "repaired": False,
    }


def _prepare_manager(cfg: Config) -> StatusManager:
    calendar = Calendar(calendar_tag=cfg.calendar_tag, overrides_path=cfg.calendar_path)
    validator = SchemaValidator(root_dir=_repo_root(), calendar=calendar)
    publisher = DummyPublisher()
    manager = StatusManager(config=cfg, validator=validator, publisher=publisher, calendar=calendar)
    manager._snapshot = manager.build_initial_snapshot()
    block = _tail_guard_block()
    manager._snapshot["tail_guard"] = {
        **block,
        "near": dict(block),
        "far": dict(block),
    }
    return manager


def _extract_payload(manager: StatusManager) -> Dict[str, Any]:
    manager.publish_snapshot()
    publisher = manager.publisher
    assert isinstance(publisher, DummyPublisher)
    payload_json = publisher.publish_json
    assert payload_json is not None
    return cast(Dict[str, Any], json.loads(payload_json))


def test_status_payload_soft_compact_disabled_detail() -> None:
    base_cfg = Config()
    cfg = replace(base_cfg, status_tail_guard_detail_enabled=False, status_soft_limit_bytes=6500)
    manager = _prepare_manager(cfg)
    payload = _extract_payload(manager)
    manager.validator.validate_status_v2(payload)
    assert "tail_guard_summary" in payload
    assert "tail_guard" not in payload
    assert "status_soft_compact_tail_guard" not in payload.get("degraded", [])


def test_status_payload_soft_compact_over_limit() -> None:
    base_cfg = Config()
    cfg = replace(base_cfg, status_tail_guard_detail_enabled=True, status_soft_limit_bytes=200)
    manager = _prepare_manager(cfg)
    payload = _extract_payload(manager)
    manager.validator.validate_status_v2(payload)
    assert "tail_guard_summary" in payload
    assert "tail_guard" not in payload
    assert "status_soft_compact_tail_guard" in payload.get("degraded", [])
