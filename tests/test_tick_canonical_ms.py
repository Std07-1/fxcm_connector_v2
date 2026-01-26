from __future__ import annotations

import pytest

from core.market.tick import normalize_tick
from core.validation.validator import ContractError


def test_tick_rejects_seconds_timestamp() -> None:
    with pytest.raises(ContractError):
        normalize_tick(
            symbol="XAUUSD",
            bid=2000.0,
            ask=2000.2,
            tick_ts_ms=1_700_000_000,
            snap_ts_ms=1_700_000_000,
        )


def test_tick_rejects_float_timestamp() -> None:
    with pytest.raises(ContractError):
        normalize_tick(
            symbol="XAUUSD",
            bid=2000.0,
            ask=2000.2,
            tick_ts_ms=1_700_000_000_000.5,  # type: ignore[arg-type]
            snap_ts_ms=1_700_000_000_001.0,  # type: ignore[arg-type]
        )


def test_tick_accepts_ms_timestamp() -> None:
    tick = normalize_tick(
        symbol="XAUUSD",
        bid=2000.0,
        ask=2000.2,
        tick_ts_ms=1_700_000_000_000,
        snap_ts_ms=1_700_000_000_123,
    )
    assert tick.tick_ts_ms == 1_700_000_000_000
    assert tick.snap_ts_ms == 1_700_000_000_123
