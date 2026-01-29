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
from core.time.sessions import _parse_hhmm, _resolve_tz_or_raise


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
        ok, msg = _require_keys(
            entry,
            ("weekly_open", "weekly_close", "daily_break_start", "daily_break_minutes", "tz_name"),
        )
        if not ok:
            return False, msg
        if not isinstance(entry.get("tz_name"), str):
            return False, f"calendar_tag={tag}: tz_name має бути рядком"
        if not isinstance(entry.get("weekly_open"), str) or not isinstance(entry.get("weekly_close"), str):
            return False, f"calendar_tag={tag}: weekly_open/weekly_close мають бути рядками HH:MM"
        if not isinstance(entry.get("daily_break_start"), str):
            return False, f"calendar_tag={tag}: daily_break_start має бути рядком HH:MM"
        daily_break_minutes = entry.get("daily_break_minutes")
        if not isinstance(daily_break_minutes, int) or isinstance(daily_break_minutes, bool):
            return False, f"calendar_tag={tag}: daily_break_minutes має бути int"
        if int(daily_break_minutes) <= 0:
            return False, f"calendar_tag={tag}: daily_break_minutes має бути > 0"
        try:
            _parse_hhmm(str(entry.get("weekly_open")))
            _parse_hhmm(str(entry.get("weekly_close")))
            _parse_hhmm(str(entry.get("daily_break_start")))
            _resolve_tz_or_raise(str(entry.get("tz_name")))
        except Exception as exc:  # noqa: BLE001
            return False, f"calendar_tag={tag}: {exc}"

        raw_intervals = entry.get("closed_intervals_utc", [])
        try:
            normalize_closed_intervals_utc(list(raw_intervals) if raw_intervals is not None else [])
        except Exception as exc:  # noqa: BLE001
            return False, f"calendar_tag={tag}: {exc}"

    return True, "OK: calendar_overrides валідні (closed_intervals_utc + schedule keys)"
