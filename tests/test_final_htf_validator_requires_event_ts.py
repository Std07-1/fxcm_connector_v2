from __future__ import annotations

from pathlib import Path

import pytest

from core.validation.validator import ContractError, SchemaValidator


def test_final_htf_validator_requires_event_ts() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    base = 1_736_980_000_000
    open_time = base - (base % 900_000)
    close_time = open_time + 900_000 - 1
    payload = {
        "symbol": "XAUUSD",
        "tf": "15m",
        "source": "history_agg",
        "complete": True,
        "synthetic": False,
        "bars": [
            {
                "open_time": open_time,
                "close_time": close_time,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "volume": 10.0,
                "complete": True,
                "synthetic": False,
                "source": "history_agg",
            }
        ],
    }
    with pytest.raises(ContractError):
        validator.validate_ohlcv_final_htf_batch(payload)
