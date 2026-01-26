from __future__ import annotations

from pathlib import Path


def test_ui_gap_insert_whitespace_scan() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "ui_lite" / "static" / "chart_adapter.js"
    text = path.read_text(encoding="utf-8")
    assert "function insertWhitespace" in text
    assert "while (cursor < bar.time)" in text
    assert "output.push({ time:" in text
