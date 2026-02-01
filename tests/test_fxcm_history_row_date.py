from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.validation.validator import ContractError
from runtime.fxcm.history_provider import _rows_to_bars


def test_history_row_date_case_insensitive() -> None:
    rows = [
        {
            "Date": datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
            "open": 1.0,
            "high": 1.2,
            "low": 0.9,
            "close": 1.1,
            "volume": 10,
        }
    ]
    bars = _rows_to_bars("XAUUSD", rows, limit=10)
    assert len(bars) == 1
    assert int(bars[0]["open_time_ms"]) > 0


def test_history_row_missing_date_fail_fast() -> None:
    rows = [
        {
            "open": 1.0,
            "high": 1.2,
            "low": 0.9,
            "close": 1.1,
            "volume": 10,
        }
    ]
    with pytest.raises(ContractError, match="history_row_missing_date"):
        _rows_to_bars("XAUUSD", rows, limit=10)
