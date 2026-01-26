from __future__ import annotations

from pathlib import Path

import pytest

from core.validation.validator import ContractError, SchemaValidator


def test_tick_v1_valid_ms() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    payload = {
        "symbol": "XAUUSD",
        "bid": 2000.0,
        "ask": 2000.2,
        "mid": 2000.1,
        "tick_ts": 1_736_980_000_000,
        "snap_ts": 1_736_980_000_001,
    }
    validator.validate_tick_v1(payload)


def test_tick_v1_float_rejected() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    payload = {
        "symbol": "XAUUSD",
        "bid": 2000.0,
        "ask": 2000.2,
        "mid": 2000.1,
        "tick_ts": 1.5,
        "snap_ts": 1_736_980_000_000,
    }
    with pytest.raises(ContractError):
        validator.validate_tick_v1(payload)


def test_tick_v1_seconds_rejected() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    payload = {
        "symbol": "XAUUSD",
        "bid": 2000.0,
        "ask": 2000.2,
        "mid": 2000.1,
        "tick_ts": 1_736_980_000,
        "snap_ts": 1_736_980_000,
    }
    with pytest.raises(ContractError):
        validator.validate_tick_v1(payload)


def test_tick_v1_microseconds_rejected() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    payload = {
        "symbol": "XAUUSD",
        "bid": 2000.0,
        "ask": 2000.2,
        "mid": 2000.1,
        "tick_ts": 1_736_980_000_000_000,
        "snap_ts": 1_736_980_000_000_000,
    }
    with pytest.raises(ContractError):
        validator.validate_tick_v1(payload)


def test_tick_v1_extra_field_rejected() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    payload = {
        "symbol": "XAUUSD",
        "bid": 2000.0,
        "ask": 2000.2,
        "mid": 2000.1,
        "tick_ts": 1_736_980_000_000,
        "snap_ts": 1_736_980_000_000,
        "extra": 123,
    }
    with pytest.raises(ContractError):
        validator.validate_tick_v1(payload)


def test_tick_schema_int_accepts_ms() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    payload = {
        "symbol": "XAUUSD",
        "bid": 2000.0,
        "ask": 2000.2,
        "mid": 2000.1,
        "tick_ts": 1_736_980_000_000,
        "snap_ts": 1_736_980_000_001,
    }
    validator.validate("core/contracts/public/tick_v1.json", payload)


def test_tick_schema_float_rejected() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    payload = {
        "symbol": "XAUUSD",
        "bid": 2000.0,
        "ask": 2000.2,
        "mid": 2000.1,
        "tick_ts": 1.5,
        "snap_ts": 1_736_980_000_000,
    }
    with pytest.raises(ContractError):
        validator.validate("core/contracts/public/tick_v1.json", payload)
