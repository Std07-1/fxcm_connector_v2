from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from tools.run_exit_gates import fail_direct_gate_run

    fail_direct_gate_run("gate_calendar_schedule_drift")

from datetime import datetime, timezone, tzinfo
from typing import Tuple, cast

from config.config import load_config
from core.time import sessions
from core.time.calendar import Calendar
from core.time.sessions import load_calendar_overrides
from core.time.timestamps import to_epoch_ms_utc


def _parse_hhmm(value: str) -> Tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("час має формат HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("час має коректні межі")
    return hour, minute


def _resolve_tz(tz_name: str) -> tzinfo:
    if tz_name.upper() == "UTC" or tz_name == "Etc/UTC":
        return timezone.utc
    if sessions.ZoneInfo is not None:
        try:
            return cast(tzinfo, sessions.ZoneInfo(tz_name))
        except Exception:  # noqa: BLE001
            pass
    fallback = sessions._tz.gettz(tz_name)
    if fallback is None:
        return timezone.utc
    return cast(tzinfo, fallback)


def _ms_local(year: int, month: int, day: int, hour: int, minute: int, tz: tzinfo) -> int:
    dt_local = datetime(year, month, day, hour, minute, tzinfo=tz)
    dt_utc = dt_local.astimezone(timezone.utc)
    return to_epoch_ms_utc(dt_utc)


def run() -> Tuple[bool, str]:
    config = load_config()
    calendar = Calendar([], config.calendar_tag)
    if calendar.health_error():
        return False, f"FAIL: calendar init_error: {calendar.health_error()}"
    try:
        overrides = load_calendar_overrides(
            repo_root=Path(__file__).resolve().parents[3],
            tag=config.calendar_tag,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"FAIL: overrides loader error: {exc}"

    tz = _resolve_tz(overrides.tz_name)
    break_h, break_m = _parse_hhmm(overrides.daily_break_start)
    break_start_ms = _ms_local(2026, 1, 7, break_h, break_m, tz)
    before_break_ms = break_start_ms - 60_000
    during_break_ms = break_start_ms + 60_000

    if not calendar.is_open(before_break_ms):
        return (
            False,
            "FAIL: daily break drift (очікував OPEN перед break) "
            f"tag={overrides.calendar_tag} tz={overrides.tz_name} "
            f"before_ms={before_break_ms} break_start_ms={break_start_ms}",
        )
    if calendar.is_open(during_break_ms):
        return (
            False,
            "FAIL: daily break drift (очікував CLOSED під час break) "
            f"tag={overrides.calendar_tag} tz={overrides.tz_name} "
            f"during_ms={during_break_ms} break_start_ms={break_start_ms}",
        )

    close_h, close_m = _parse_hhmm(overrides.weekly_close)
    open_h, open_m = _parse_hhmm(overrides.weekly_open)
    close_ms = _ms_local(2026, 1, 9, close_h, close_m, tz)
    open_ms = _ms_local(2026, 1, 11, open_h, open_m, tz)

    if calendar.is_open(close_ms + 60_000):
        return (
            False,
            "FAIL: weekly close drift (очікував CLOSED після close) "
            f"tag={overrides.calendar_tag} tz={overrides.tz_name} "
            f"close_ms={close_ms}",
        )
    if not calendar.is_open(open_ms + 60_000):
        return (
            False,
            "FAIL: weekly open drift (очікував OPEN після open) "
            f"tag={overrides.calendar_tag} tz={overrides.tz_name} "
            f"open_ms={open_ms}",
        )

    return True, "OK: schedule drift gate (daily break + weekly boundary)"
