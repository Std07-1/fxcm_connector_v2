from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, cast

import pytest

from core.validation.validator import ContractError, SchemaValidator


def test_final_bar_invariants() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    base = 1_736_980_000_000
    open_time = base - (base % 60_000)
    close_time = open_time + 60_000 - 1
    last_complete_bar_ms = close_time
    assert last_complete_bar_ms % 60_000 == 59_999
    payload = {
        "symbol": "XAUUSD",
        "tf": "1m",
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
                "volume": 1.0,
                "complete": True,
                "synthetic": False,
                "source": "history",
                "event_ts": close_time,
            }
        ],
    }
    validator.validate_ohlcv_v1(payload, max_bars_per_message=512)

    bars = cast(List[Dict[str, Any]], payload["bars"])
    bars[0]["event_ts"] = open_time
    with pytest.raises(ContractError):
        validator.validate_ohlcv_v1(payload, max_bars_per_message=512)
