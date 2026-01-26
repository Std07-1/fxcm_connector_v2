from __future__ import annotations

from ui_lite import server


def _reset_buffers() -> None:
    server._RING_BUFFERS.clear()
    server._DEDUP_KEYS.clear()


def test_normalize_bar_time_seconds() -> None:
    payload = {"symbol": "XAUUSD", "tf": "1m"}
    bar = {
        "open_time_ms": 171000,
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 10.0,
    }
    out = server._normalize_bar(payload, bar)
    assert out is not None
    assert out["time"] == 171
    assert out["open"] == 1.0
    assert out["high"] == 2.0
    assert out["low"] == 0.5
    assert out["close"] == 1.5
    assert out["volume"] == 10.0


def test_snapshot_filters_by_key() -> None:
    _reset_buffers()
    payload = {"symbol": "XAUUSD", "tf": "1m"}
    bar = {
        "open_time_ms": 171000,
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
    }
    norm = server._normalize_bar(payload, bar)
    assert norm is not None
    assert server._buffer_bar("XAUUSD", "1m", "preview", norm, 171000) is True
    assert server._buffer_bar("XAUUSD", "1m", "final", norm, 171000) is True
    assert server._buffer_bar("XAUUSD", "5m", "preview", norm, 171000) is True

    snapshot_preview = server._snapshot_for("XAUUSD", "1m", "preview")
    snapshot_final = server._snapshot_for("XAUUSD", "1m", "final")
    snapshot_tf = server._snapshot_for("XAUUSD", "5m", "preview")

    assert len(snapshot_preview) == 1
    assert len(snapshot_final) == 1
    assert len(snapshot_tf) == 1
