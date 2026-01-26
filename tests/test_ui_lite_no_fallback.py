from __future__ import annotations

from ui_lite.server import _parse_subscribe


def test_ui_lite_subscribe_missing_symbol() -> None:
    symbol, tf, mode, err = _parse_subscribe({"type": "subscribe", "tf": "1m"})
    assert symbol is None
    assert tf is None
    assert mode == "preview"
    assert err is not None
    assert err.get("code") == "missing_symbol"


def test_ui_lite_subscribe_missing_tf() -> None:
    symbol, tf, mode, err = _parse_subscribe({"type": "subscribe", "symbol": "XAUUSD"})
    assert symbol is None
    assert tf is None
    assert mode == "preview"
    assert err is not None
    assert err.get("code") == "missing_tf"
