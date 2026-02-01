from __future__ import annotations

from pathlib import Path

import pytest

from core.validation.validator import ContractError, SchemaValidator


def test_final_source_allowlist_enforced() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    payload = {
        "symbol": "XAUUSD",
        "tf": "1m",
        "source": "stream",
        "complete": True,
        "synthetic": False,
        "bars": [
            {
                "open_time": 1_700_000_000_000,
                "close_time": 1_700_000_060_000 - 1,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "volume": 1.0,
                "complete": True,
                "synthetic": False,
                "source": "stream",
                "event_ts": 1_700_000_060_000 - 1,
            }
        ],
    }
    with pytest.raises(ContractError):
        validator.validate_ohlcv_v1(payload, max_bars_per_message=512)
