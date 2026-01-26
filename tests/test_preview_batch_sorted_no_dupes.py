from __future__ import annotations

from pathlib import Path

import pytest

from core.validation.validator import ContractError, SchemaValidator


def test_preview_batch_sorted_no_dupes() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    payload = {
        "symbol": "XAUUSD",
        "tf": "1m",
        "source": "stream",
        "bars": [
            {
                "open_time": 1_736_980_000_000,
                "close_time": 1_736_980_059_999,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "volume": 1.0,
            },
            {
                "open_time": 1_736_980_000_000,
                "close_time": 1_736_980_059_999,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "volume": 1.0,
            },
        ],
    }
    with pytest.raises(ContractError):
        validator.validate_ohlcv_preview_batch(payload)

    payload["bars"] = list(reversed(payload["bars"]))
    with pytest.raises(ContractError):
        validator.validate_ohlcv_preview_batch(payload)


def test_preview_batch_synthetic_rejected() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    payload = {
        "symbol": "XAUUSD",
        "tf": "1m",
        "source": "stream",
        "bars": [
            {
                "open_time": 1_736_980_000_000,
                "close_time": 1_736_980_059_999,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "volume": 1.0,
                "synthetic": True,
            }
        ],
    }
    with pytest.raises(ContractError):
        validator.validate_ohlcv_preview_batch(payload)
