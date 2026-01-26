from __future__ import annotations

from pathlib import Path

import pytest

from core.validation.validator import ContractError, SchemaValidator


def test_final_1m_validator_accepts_valid() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    base_time = 1_736_980_000_000
    open_time = base_time - (base_time % 60_000)
    payload = {
        "symbol": "XAUUSD",
        "tf": "1m",
        "source": "history",
        "complete": True,
        "synthetic": False,
        "bars": [
            {
                "open_time": open_time,
                "close_time": open_time + 60_000 - 1,
                "open": 1.0,
                "high": 1.2,
                "low": 0.9,
                "close": 1.1,
                "volume": 1.0,
                "complete": True,
                "synthetic": False,
                "source": "history",
            }
        ],
    }
    validator.validate_ohlcv_final_1m_batch(payload)


def test_final_1m_validator_rejects_complete_false() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    base_time = 1_736_980_000_000
    open_time = base_time - (base_time % 60_000)
    payload = {
        "symbol": "XAUUSD",
        "tf": "1m",
        "source": "history",
        "complete": True,
        "synthetic": False,
        "bars": [
            {
                "open_time": open_time,
                "close_time": open_time + 60_000 - 1,
                "open": 1.0,
                "high": 1.2,
                "low": 0.9,
                "close": 1.1,
                "volume": 1.0,
                "complete": False,
                "synthetic": False,
                "source": "history",
            }
        ],
    }
    with pytest.raises(ContractError):
        validator.validate_ohlcv_final_1m_batch(payload)
