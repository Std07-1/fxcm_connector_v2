from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from core.time.closed_intervals import normalize_closed_intervals_utc


def _parse_iso_to_ms(value: str) -> int:
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def _holiday_to_interval_ms(value: str) -> List[int]:
    dt = datetime.fromisoformat(value)
    dt = dt.replace(tzinfo=timezone.utc)
    start_ms = int(dt.timestamp() * 1000)
    end_ms = int((dt + timedelta(days=1)).timestamp() * 1000)
    return [start_ms, end_ms]


def _find_v1_path(repo_root: Path) -> Path:
    candidate = repo_root / "config" / "v1_calendar_overrides.json"
    if candidate.exists():
        return candidate
    matches = list(repo_root.rglob("v1_calendar_overrides.json"))
    if not matches:
        raise FileNotFoundError("v1_calendar_overrides.json не знайдено")
    return matches[0]


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    v1_path = _find_v1_path(repo_root)
    v1_data = json.loads(v1_path.read_text(encoding="utf-8"))

    intervals: List[List[int]] = []
    raw_intervals = v1_data.get("closed_intervals_utc", [])
    if not isinstance(raw_intervals, list):
        raise ValueError("v1 closed_intervals_utc має бути списком")
    for idx, item in enumerate(raw_intervals):
        if not isinstance(item, dict):
            raise ValueError(f"v1 closed_intervals_utc[{idx}] має бути об'єктом")
        start = item.get("start")
        end = item.get("end")
        if not isinstance(start, str) or not isinstance(end, str):
            raise ValueError(f"v1 closed_intervals_utc[{idx}] має start/end рядками")
        intervals.append([_parse_iso_to_ms(start), _parse_iso_to_ms(end)])

    holidays = v1_data.get("holidays", [])
    if not isinstance(holidays, list):
        raise ValueError("v1 holidays має бути списком")
    for idx, day in enumerate(holidays):
        if not isinstance(day, str):
            raise ValueError(f"v1 holidays[{idx}] має бути рядком")
        intervals.append(_holiday_to_interval_ms(day))

    normalized = normalize_closed_intervals_utc(intervals)

    overrides_path = repo_root / "config" / "calendar_overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    if not isinstance(overrides, list):
        raise ValueError("calendar_overrides.json має бути списком профілів")

    found = False
    for entry in overrides:
        if isinstance(entry, dict) and entry.get("calendar_tag") == "fxcm_calendar_v1_utc_overrides":
            entry["closed_intervals_utc"] = normalized
            found = True
            break
    if not found:
        raise ValueError("calendar_tag fxcm_calendar_v1_utc_overrides не знайдено")

    overrides_path.write_text(json.dumps(overrides, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK: міграція v1 → calendar_overrides.json (intervals={len(normalized)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
