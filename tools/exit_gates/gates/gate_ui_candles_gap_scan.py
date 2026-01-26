from __future__ import annotations

from pathlib import Path
from typing import Tuple


def run() -> Tuple[bool, str]:
    root = Path(__file__).resolve().parents[3]
    app_path = root / "ui_lite" / "static" / "app.js"
    adapter_path = root / "ui_lite" / "static" / "chart_adapter.js"
    index_path = root / "ui_lite" / "static" / "index.html"
    if not app_path.exists() or not adapter_path.exists() or not index_path.exists():
        return False, "Не знайдено UI Lite static файли"

    app_text = app_path.read_text(encoding="utf-8")
    adapter_text = adapter_path.read_text(encoding="utf-8")
    index_text = index_path.read_text(encoding="utf-8")

    if "addCandlestickSeries" not in app_text:
        return False, "Не знайдено addCandlestickSeries у app.js"
    if "insertWhitespace" not in adapter_text:
        return False, "Не знайдено insertWhitespace у chart_adapter.js"
    if "gapPlaceholders" not in adapter_text:
        return False, "Не знайдено gapPlaceholders у chart_adapter.js"
    if "chart_adapter.js" not in index_text:
        return False, "index.html не підключає chart_adapter.js"
    return True, "OK: UI candles + gap scan"
