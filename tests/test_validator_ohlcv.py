from __future__ import annotations

from pathlib import Path

import pytest

from core.validation.validator import ContractError, SchemaValidator


def _bar(open_time: int, close_time: int) -> dict:
    return {
        "open_time": open_time,
        "close_time": close_time,
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": 1.05,
        "volume": 10.0,
        "tick_count": 10,
        "complete": False,
        "synthetic": False,
        "source": "stream",
    }


def _aligned_open(base_ms: int, bucket_ms: int) -> int:
    return base_ms - (base_ms % bucket_ms)


def test_ohlcv_valid_preview() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    base = 1_736_980_000_000
    open_time = _aligned_open(base, 60_000)
    close_time = open_time + 60_000 - 1
    payload = {
        "symbol": "XAUUSD",
        "tf": "1m",
        "source": "stream",
        "complete": False,
        "synthetic": False,
        "bars": [_bar(open_time, close_time)],
    }
    validator.validate_ohlcv_v1(payload, max_bars_per_message=512)


def test_ohlcv_extra_field_rejected() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    base = 1_736_980_000_000
    open_time = _aligned_open(base, 60_000)
    close_time = open_time + 60_000 - 1
    payload = {
        "symbol": "XAUUSD",
        "tf": "1m",
        "source": "stream",
        "complete": False,
        "synthetic": False,
        "bars": [_bar(open_time, close_time)],
        "extra": 1,
    }
    with pytest.raises(ContractError):
        validator.validate_ohlcv_v1(payload, max_bars_per_message=512)


def test_ohlcv_seconds_rejected() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    open_time = 1_736_980_000
    close_time = open_time + 60_000 - 1
    payload = {
        "symbol": "XAUUSD",
        "tf": "1m",
        "source": "stream",
        "complete": False,
        "synthetic": False,
        "bars": [_bar(open_time, close_time)],
    }
    with pytest.raises(ContractError):
        validator.validate_ohlcv_v1(payload, max_bars_per_message=512)


def test_ohlcv_unsorted_rejected() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    base = 1_736_980_000_000
    t1 = _aligned_open(base, 60_000)
    t2 = t1 + 60_000
    payload = {
        "symbol": "XAUUSD",
        "tf": "1m",
        "source": "stream",
        "complete": False,
        "synthetic": False,
        "bars": [_bar(t2, t2 + 60_000 - 1), _bar(t1, t1 + 60_000 - 1)],
    }
    with pytest.raises(ContractError):
        validator.validate_ohlcv_v1(payload, max_bars_per_message=512)


def test_ohlcv_duplicate_open_time_rejected() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    base = 1_736_980_000_000
    t1 = _aligned_open(base, 60_000)
    payload = {
        "symbol": "XAUUSD",
        "tf": "1m",
        "source": "stream",
        "complete": False,
        "synthetic": False,
        "bars": [_bar(t1, t1 + 60_000 - 1), _bar(t1, t1 + 60_000 - 1)],
    }
    with pytest.raises(ContractError):
        validator.validate_ohlcv_v1(payload, max_bars_per_message=512)


def test_ohlcv_preview_complete_true_rejected() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    base = 1_736_980_000_000
    t1 = _aligned_open(base, 60_000)
    payload = {
        "symbol": "XAUUSD",
        "tf": "1m",
        "source": "stream",
        "complete": True,
        "synthetic": False,
        "bars": [_bar(t1, t1 + 60_000 - 1)],
    }
    with pytest.raises(ContractError):
        validator.validate_ohlcv_v1(payload, max_bars_per_message=512)


def test_ohlcv_final_htf_source_rejected() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    base = 1_736_980_000_000
    open_time = _aligned_open(base, 900_000)
    close_time = open_time + 900_000 - 1
    payload = {
        "symbol": "XAUUSD",
        "tf": "15m",
        "source": "history",
        "complete": True,
        "synthetic": False,
        "bars": [
            {
                "open_time": open_time,
                "close_time": close_time,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "volume": 10.0,
                "complete": True,
                "synthetic": False,
                "source": "history",
                "event_ts": close_time,
            }
        ],
    }
    with pytest.raises(ContractError):
        validator.validate_ohlcv_v1(payload, max_bars_per_message=512)
