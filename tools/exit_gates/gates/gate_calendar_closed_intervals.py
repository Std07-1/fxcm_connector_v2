from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from tools.run_exit_gates import fail_direct_gate_run

    fail_direct_gate_run("gate_calendar_closed_intervals")

import json
from typing import Tuple

from core.time.closed_intervals import normalize_closed_intervals_utc


def _require_keys(entry: dict, keys: Tuple[str, ...]) -> Tuple[bool, str]:
    for key in keys:
        if key not in entry:
            return False, f"відсутній ключ {key} для calendar_tag={entry.get('calendar_tag')}"
    return True, ""


def run() -> Tuple[bool, str]:
    overrides_path = Path(__file__).resolve().parents[3] / "config" / "calendar_overrides.json"
    data = json.loads(overrides_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return False, "calendar_overrides.json має бути списком профілів"

    for idx, entry in enumerate(data):
        if not isinstance(entry, dict):
            return False, f"calendar_overrides[{idx}] має бути об'єктом"
        tag = entry.get("calendar_tag")
        if not isinstance(tag, str) or not tag:
            return False, f"calendar_overrides[{idx}].calendar_tag має бути непорожнім рядком"
        raw_intervals = entry.get("closed_intervals_utc", [])
        try:
            normalize_closed_intervals_utc(list(raw_intervals) if raw_intervals is not None else [])
        except Exception as exc:  # noqa: BLE001
            return False, f"calendar_tag={tag}: {exc}"

        if tag == "fxcm_calendar_v1_utc_overrides":
            ok, msg = _require_keys(
                entry,
                ("weekly_open", "weekly_close", "daily_break_start", "daily_break_minutes", "tz_name"),
            )
            if not ok:
                return False, msg

    return True, "OK: closed_intervals_utc валідні"
