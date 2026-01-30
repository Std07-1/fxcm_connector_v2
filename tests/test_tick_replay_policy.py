from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.market.replay_policy import TickReplayPolicy, validate_jsonl
from core.time.calendar import Calendar
from core.time.timestamps import to_epoch_ms_utc
from core.validation.validator import ContractError, SchemaValidator


def _write_jsonl(path: Path, payloads: list) -> None:
    lines = [json.dumps(payload, ensure_ascii=False) for payload in payloads]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ms(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> int:
    return to_epoch_ms_utc(datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc))


def _policy() -> TickReplayPolicy:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    calendar = Calendar(calendar_tag="fxcm_calendar_v1_ny")
    return TickReplayPolicy(calendar=calendar, validator=validator)


def test_replay_out_of_order_tick_ts_rejected(tmp_path: Path) -> None:
    policy = _policy()
    path = tmp_path / "ticks.jsonl"
    payloads = [
        {
            "symbol": "XAUUSD",
            "bid": 2000.0,
            "ask": 2000.2,
            "mid": 2000.1,
            "tick_ts": 1_736_980_000_001,
            "snap_ts": 1_736_980_000_002,
        },
        {
            "symbol": "XAUUSD",
            "bid": 2000.1,
            "ask": 2000.3,
            "mid": 2000.2,
            "tick_ts": 1_736_980_000_000,
            "snap_ts": 1_736_980_000_003,
        },
    ]
    _write_jsonl(path, payloads)
    with pytest.raises(ContractError):
        validate_jsonl(path, policy)


def test_replay_closed_time_rejected(tmp_path: Path) -> None:
    policy = _policy()
    path = tmp_path / "ticks.jsonl"
    closed_tick_ts = _ms(2026, 1, 24, 12, 0, 0)  # субота
    payloads = [
        {
            "symbol": "XAUUSD",
            "bid": 2000.0,
            "ask": 2000.2,
            "mid": 2000.1,
            "tick_ts": closed_tick_ts,
            "snap_ts": closed_tick_ts + 1,
        }
    ]
    _write_jsonl(path, payloads)
    with pytest.raises(ContractError):
        validate_jsonl(path, policy)


def test_replay_equal_tick_ts_snap_ts_decreasing_rejected(tmp_path: Path) -> None:
    policy = _policy()
    path = tmp_path / "ticks.jsonl"
    payloads = [
        {
            "symbol": "XAUUSD",
            "bid": 2000.0,
            "ask": 2000.2,
            "mid": 2000.1,
            "tick_ts": 1_736_980_000_000,
            "snap_ts": 1_736_980_000_010,
        },
        {
            "symbol": "XAUUSD",
            "bid": 2000.1,
            "ask": 2000.3,
            "mid": 2000.2,
            "tick_ts": 1_736_980_000_000,
            "snap_ts": 1_736_980_000_005,
        },
    ]
    _write_jsonl(path, payloads)
    with pytest.raises(ContractError):
        validate_jsonl(path, policy)
