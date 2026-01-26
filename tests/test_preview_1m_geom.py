from __future__ import annotations

import pytest


def _check_geom(bar: dict) -> None:
    high = bar["high"]
    low = bar["low"]
    open_ = bar["open"]
    close = bar["close"]
    if high < max(open_, close):
        raise ValueError("high має бути >= max(open, close)")
    if low > min(open_, close):
        raise ValueError("low має бути <= min(open, close)")
    if high < low:
        raise ValueError("high має бути >= low")


def test_preview_geom_ok() -> None:
    bar = {"open": 2000.0, "high": 2000.5, "low": 1999.8, "close": 2000.2}
    _check_geom(bar)


def test_preview_geom_fail() -> None:
    bar = {"open": 2000.0, "high": 1999.9, "low": 2000.1, "close": 2000.2}
    with pytest.raises(ValueError):
        _check_geom(bar)
