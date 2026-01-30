from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core.time.closed_intervals import normalize_closed_intervals_utc


def _read_overrides(path: Path) -> List[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"calendar_overrides.json невалідний JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("calendar_overrides.json має містити список профілів")
    return [dict(item) for item in data if isinstance(item, dict)]


def _max_end_ms(intervals: List[Tuple[int, int]]) -> int:
    if not intervals:
        return 0
    return max(int(pair[1]) for pair in intervals)


def run() -> Tuple[bool, str]:
    repo_root = Path(__file__).resolve().parents[3]
    overrides_path = repo_root / "config" / "calendar_overrides.json"
    if not overrides_path.exists():
        return False, f"FAIL: overrides файл не знайдено: {overrides_path}"

    try:
        profiles = _read_overrides(overrides_path)
    except Exception as exc:  # noqa: BLE001
        return False, f"FAIL: {exc}"

    now_ms = int(time.time() * 1000)
    for entry in profiles:
        tag = str(entry.get("calendar_tag", ""))
        policy = entry.get("holiday_policy")
        if not isinstance(policy, dict):
            return False, f"FAIL: holiday_policy відсутній або не dict для {tag or '<unknown>'}"

        coverage_end = policy.get("coverage_end_utc")
        min_intervals = policy.get("min_intervals")
        required = policy.get("required")
        min_future_days = policy.get("min_future_days")
        if not isinstance(coverage_end, int) or isinstance(coverage_end, bool):
            return False, f"FAIL: holiday_policy.coverage_end_utc має бути int для {tag}"
        if not isinstance(min_intervals, int) or isinstance(min_intervals, bool):
            return False, f"FAIL: holiday_policy.min_intervals має бути int для {tag}"
        if not isinstance(required, bool):
            return False, f"FAIL: holiday_policy.required має бути bool для {tag}"
        if not isinstance(min_future_days, int) or isinstance(min_future_days, bool):
            return False, f"FAIL: holiday_policy.min_future_days має бути int для {tag}"
        if min_future_days < 0:
            return False, f"FAIL: holiday_policy.min_future_days має бути >= 0 для {tag}"
        if min_intervals <= 0:
            return False, f"FAIL: holiday_policy.min_intervals має бути > 0 для {tag}"

        raw_intervals = entry.get("closed_intervals_utc", [])
        if not isinstance(raw_intervals, list):
            return False, f"FAIL: closed_intervals_utc має бути списком для {tag}"

        try:
            normalized = normalize_closed_intervals_utc(raw_intervals)
        except Exception as exc:  # noqa: BLE001
            return False, f"FAIL: closed_intervals_utc невалідні для {tag}: {exc}"

        if len(normalized) < min_intervals:
            return False, (f"FAIL: closed_intervals_utc менше мінімуму ({len(normalized)} < {min_intervals}) для {tag}")

        max_end = _max_end_ms([(int(a), int(b)) for a, b in normalized])
        if max_end != coverage_end:
            return False, f"FAIL: coverage_end_utc має дорівнювати max(end_ms) для {tag}"
        if required is True and min_future_days > 0:
            required_end = now_ms + int(min_future_days) * 86_400_000
            if coverage_end < required_end:
                return False, (f"FAIL: coverage_end_utc не покриває min_future_days для {tag}")

    return True, "OK: holiday_policy присутній і покриття closed_intervals_utc відповідає політиці"
