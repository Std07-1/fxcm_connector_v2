from __future__ import annotations

from typing import Tuple

from config.config import Config
from core.time.calendar import Calendar


def run() -> Tuple[bool, str]:
    config = Config()
    if not hasattr(config, "calendar_tag") or not hasattr(config, "calendar_path"):
        return False, "FAIL: Config має містити calendar_tag і calendar_path"
    if hasattr(config, "trading_day_boundary_utc"):
        return False, "FAIL: trading_day_boundary_utc не має існувати у Config"
    if hasattr(config, "closed_intervals_utc"):
        return False, "FAIL: closed_intervals_utc не має існувати у Config"

    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    if calendar.health_error():
        return False, f"FAIL: Calendar.init_error: {calendar.health_error()}"

    return True, "OK: FXCM календар бере SSOT з calendar_overrides.json (Config без дублювань)"
