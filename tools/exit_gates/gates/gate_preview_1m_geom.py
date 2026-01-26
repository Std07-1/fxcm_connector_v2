from __future__ import annotations

import json
from typing import Any, Dict, Tuple

from core.fixtures_path import fixture_path


def _check_bar(bar: Dict[str, Any]) -> None:
    high = bar.get("high")
    low = bar.get("low")
    open_ = bar.get("open")
    close = bar.get("close")
    if not isinstance(high, (int, float)):
        raise ValueError("high має бути числом")
    if not isinstance(low, (int, float)):
        raise ValueError("low має бути числом")
    if not isinstance(open_, (int, float)):
        raise ValueError("open має бути числом")
    if not isinstance(close, (int, float)):
        raise ValueError("close має бути числом")
    if high < max(open_, close):
        raise ValueError("high має бути >= max(open, close)")
    if low > min(open_, close):
        raise ValueError("low має бути <= min(open, close)")
    if high < low:
        raise ValueError("high має бути >= low")


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

    return True, "OK: preview 1m geom інваріанти виконані"
