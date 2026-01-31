from __future__ import annotations

from pathlib import Path
from typing import Tuple


def run() -> Tuple[bool, str]:
    repo_root = Path(__file__).resolve().parents[3]
    target = repo_root / "runtime" / "fxcm_forexconnect.py"
    if not target.exists():
        return False, "FAIL: runtime/fxcm_forexconnect.py не знайдено"
    try:
        text = target.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        return False, f"FAIL: не вдалося прочитати runtime/fxcm_forexconnect.py: {exc}"

    sanitized = text.replace("_calendar_next_open_ms(", "")
    forbidden = ["_next_open_ms(", "closed_intervals_utc", "config.closed_intervals_utc"]
    hits = [token for token in forbidden if token in sanitized]
    if hits:
        return False, "FAIL: market-closed має бути через Calendar SSOT, знайдено: " + ", ".join(hits)

    if "_calendar_next_open_ms(" not in text:
        return False, "FAIL: відсутній виклик _calendar_next_open_ms() у FXCM stream"

    return True, "OK: market-closed sleep використовує Calendar SSOT через _calendar_next_open_ms"
