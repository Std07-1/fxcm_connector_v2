from __future__ import annotations

from ui_lite.server import DedupIndex


def test_dedup_keeps_first_bar() -> None:
    dedup = DedupIndex()
    assert dedup.add_if_new("XAUUSD", "1m", 1000) is True
    assert dedup.add_if_new("XAUUSD", "1m", 1000) is False
