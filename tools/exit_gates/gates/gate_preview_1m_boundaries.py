from __future__ import annotations

import json
from typing import Any, Dict, Tuple

from core.fixtures_path import fixture_path


def _check_bar(bar: Dict[str, Any]) -> None:
    open_time = bar.get("open_time")
    close_time = bar.get("close_time")
    if not isinstance(open_time, int):
        raise ValueError("open_time має бути int")
    if not isinstance(close_time, int):
        raise ValueError("close_time має бути int")
    if open_time % 60_000 != 0:
        raise ValueError("open_time має бути кратним 60000")
    expected_close = open_time + 60_000 - 1
    if close_time != expected_close:
        raise ValueError("close_time має дорівнювати open_time + 59999")


def run() -> Tuple[bool, str]:
    fixture = fixture_path("ohlcv_preview_1m_sample.json")
    if not fixture.exists():
        return False, "FAIL: ohlcv_preview_1m_sample.json відсутній"
    try:
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        bars = payload.get("bars", [])
        if not isinstance(bars, list) or not bars:
            return False, "FAIL: bars має бути непорожнім списком"
        for bar in bars:
            _check_bar(bar)
    except (ValueError, json.JSONDecodeError) as exc:
        return False, f"FAIL: {exc}"

    return True, "OK: preview 1m boundaries коректні"
