from __future__ import annotations

from pathlib import Path
from typing import Tuple


def _count_occurrences(text: str, needle: str) -> int:
    return text.count(needle)


def run() -> Tuple[bool, str]:
    root = Path(__file__).resolve().parents[3]
    path = root / "ui_lite" / "static" / "chart_adapter.js"
    if not path.exists():
        return False, "Не знайдено ui_lite/static/chart_adapter.js"
    text = path.read_text(encoding="utf-8")

    if "insertWhitespace" not in text:
        return False, "Не знайдено insertWhitespace у chart_adapter.js"
    if _count_occurrences(text, "insertWhitespace") < 1:
        return False, "insertWhitespace не знайдено у chart_adapter.js"
    if "output.push({ time:" not in text:
        return False, "Не знайдено вставку whitespace барів"
    return True, "OK: UI Lite gap visualization scan"
