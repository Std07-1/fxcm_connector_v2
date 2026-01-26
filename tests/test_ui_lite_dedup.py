from __future__ import annotations

from ui_lite.server import DedupIndex, build_dedup_key


def test_ui_lite_dedup_by_symbol_tf_open_time() -> None:
    payload = {"symbol": "XAUUSD", "tf": "1m"}
    bar = {"open_time": 1000}
    dedup = DedupIndex()

    key = build_dedup_key(payload, bar)
    assert key is not None

    assert dedup.add_if_new(*key) is True
    assert dedup.add_if_new(*key) is False
