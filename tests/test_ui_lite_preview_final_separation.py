from __future__ import annotations

from ui_lite.server import is_final_bar, is_preview_bar


def test_ui_lite_preview_final_separation() -> None:
    payload_final = {"complete": True}
    bar_final = {"open_time": 1000, "complete": True}
    assert is_final_bar(payload_final, bar_final) is True
    assert is_preview_bar(payload_final, bar_final) is False

    payload_preview = {"complete": False}
    bar_preview = {"open_time": 1000}
    assert is_final_bar(payload_preview, bar_preview) is False
    assert is_preview_bar(payload_preview, bar_preview) is True
