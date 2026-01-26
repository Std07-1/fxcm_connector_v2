from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.time.sessions import TradingCalendar

DEFAULT_RECURRENCE_TZ = "America/New_York"
DEFAULT_WEEKLY_OPEN_LOCAL = "17:00"
DEFAULT_WEEKLY_CLOSE_LOCAL = "17:00"
DEFAULT_DAILY_BREAK_START_LOCAL = "17:00"
DEFAULT_DAILY_BREAK_END_LOCAL = "17:05"


def _parse_hhmm(value: str) -> Tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("час має формат HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("час має коректні межі")
    return hour, minute


def _minutes_between(start_hhmm: str, end_hhmm: str) -> int:
    start_h, start_m = _parse_hhmm(start_hhmm)
    end_h, end_m = _parse_hhmm(end_hhmm)
    start_total = start_h * 60 + start_m
    end_total = end_h * 60 + end_m
    if end_total <= start_total:
        raise ValueError("кінець daily break має бути після початку")
    return end_total - start_total


def _load_calendar_overrides() -> Tuple[Dict[str, object], Optional[str]]:
    overrides_path = Path(__file__).resolve().parents[2] / "config" / "calendar_overrides.json"
    if not overrides_path.exists():
        return {}, f"calendar_overrides.json не знайдено: {overrides_path}"
    try:
        data = json.loads(overrides_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {}, f"calendar_overrides.json невалідний JSON: {exc}"
    if not isinstance(data, dict):
        return {}, "calendar_overrides.json має містити об'єкт"
    return data, None


@dataclass
class Calendar:
    """SSOT календар з підтримкою сесій та daily break (DST-aware)."""

    closed_intervals_utc: List[Tuple[int, int]]
    calendar_tag: str
    _calendar: TradingCalendar = field(init=False, repr=False)
    _calendars: Dict[str, TradingCalendar] = field(init=False, repr=False)
    _profile_tags: Dict[str, str] = field(init=False, repr=False)
    _symbol_profiles: Dict[str, str] = field(init=False, repr=False)
    _default_profile: str = field(init=False, repr=False)
    _init_error: Optional[str] = field(init=False, default=None)

    def __post_init__(self) -> None:
        overrides, error = _load_calendar_overrides()
        if error:
            self._init_error = error

        if any(key in overrides for key in ["weekly_open_utc", "weekly_close_utc", "daily_break_utc"]):
            self._init_error = self._init_error or "UTC recurrence заборонена: використовуйте NY local rules"

        overrides_closed = overrides.get("closed_intervals_utc", [])
        closed_intervals: List[Tuple[int, int]] = []
        if isinstance(overrides_closed, list):
            for interval in overrides_closed:
                if (
                    isinstance(interval, (list, tuple))
                    and len(interval) == 2
                    and all(isinstance(v, int) and not isinstance(v, bool) for v in interval)
                ):
                    closed_intervals.append((int(interval[0]), int(interval[1])))
                else:
                    self._init_error = self._init_error or "closed_intervals_utc має містити пари int ms"
        else:
            self._init_error = self._init_error or "closed_intervals_utc має бути списком"
        closed_intervals.extend(self.closed_intervals_utc)

        self._calendars = {}
        self._profile_tags = {}
        self._symbol_profiles = {}
        profiles = overrides.get("calendar_profiles")
        default_profile = overrides.get("default_calendar_profile")
        if isinstance(default_profile, str) and default_profile:
            self._default_profile = default_profile
        else:
            self._default_profile = "default_fx" if isinstance(profiles, dict) else "default"

        if isinstance(profiles, dict):
            for name, profile in profiles.items():
                if not isinstance(profile, dict):
                    self._init_error = self._init_error or "calendar_profiles має містити об'єкти профілів"
                    continue
                cal = self._build_profile_calendar(
                    profile=profile,
                    fallback_tag=str(overrides.get("calendar_tag", self.calendar_tag)),
                    closed_intervals=closed_intervals,
                )
                self._calendars[str(name)] = cal
                self._profile_tags[str(name)] = cal.calendar_tag
                if cal.init_error and not self._init_error:
                    self._init_error = cal.init_error
        else:
            cal = self._build_profile_calendar(
                profile=overrides,
                fallback_tag=str(overrides.get("calendar_tag", self.calendar_tag)),
                closed_intervals=closed_intervals,
            )
            self._calendars[self._default_profile] = cal
            self._profile_tags[self._default_profile] = cal.calendar_tag
            if cal.init_error and not self._init_error:
                self._init_error = cal.init_error

        symbol_profiles = overrides.get("symbol_calendar_profile", {})
        if isinstance(symbol_profiles, dict):
            for symbol, profile in symbol_profiles.items():
                if isinstance(symbol, str) and isinstance(profile, str):
                    self._symbol_profiles[symbol] = profile
        else:
            self._init_error = self._init_error or "symbol_calendar_profile має бути об'єктом"

        if self._default_profile in self._calendars:
            self._calendar = self._calendars[self._default_profile]
        elif self._calendars:
            first_profile = next(iter(self._calendars.keys()))
            self._default_profile = first_profile
            self._calendar = self._calendars[first_profile]
        else:
            self._calendar = TradingCalendar(
                closed_intervals_utc=closed_intervals,
                calendar_tag=self.calendar_tag,
            )

    def health_error(self) -> Optional[str]:
        return self._init_error or self._calendar.init_error

    def is_open(self, ts_ms: int, symbol: Optional[str] = None) -> bool:
        return self._select_calendar(symbol).is_trading_time(ts_ms)

    def market_state(self, ts_ms: int, symbol: Optional[str] = None) -> Dict[str, object]:
        return self._select_calendar(symbol).market_state(ts_ms)

    def next_open_ms(self, ts_ms: int, symbol: Optional[str] = None) -> int:
        return self._select_calendar(symbol).next_trading_open_ms(ts_ms)

    def next_pause_ms(self, ts_ms: int, symbol: Optional[str] = None) -> int:
        return self._select_calendar(symbol).next_trading_pause_ms(ts_ms)

    def explain(self, ts_ms: int, symbol: Optional[str] = None) -> List[str]:
        return self._select_calendar(symbol).explain(ts_ms)

    def is_repair_window(self, now_ms: int, safe_only_when_market_closed: bool) -> bool:
        """Дозволяє repair лише у дозволеному вікні."""
        if not safe_only_when_market_closed:
            return True
        return not self.is_open(now_ms)

    def _select_calendar(self, symbol: Optional[str]) -> TradingCalendar:
        if symbol and symbol in self._symbol_profiles:
            profile = self._symbol_profiles[symbol]
            if profile in self._calendars:
                return self._calendars[profile]
        return self._calendar

    def _build_profile_calendar(
        self,
        profile: Dict[str, object],
        fallback_tag: str,
        closed_intervals: List[Tuple[int, int]],
    ) -> TradingCalendar:
        recurrence_tz = profile.get("recurrence_tz", DEFAULT_RECURRENCE_TZ)
        if not isinstance(recurrence_tz, str) or not recurrence_tz:
            self._init_error = self._init_error or "recurrence_tz має бути непорожнім рядком"
            recurrence_tz = DEFAULT_RECURRENCE_TZ
        weekly_open = profile.get("weekly_open_local", DEFAULT_WEEKLY_OPEN_LOCAL)
        weekly_close = profile.get("weekly_close_local", DEFAULT_WEEKLY_CLOSE_LOCAL)
        daily_break = profile.get("daily_break_local", {})
        daily_break_start = DEFAULT_DAILY_BREAK_START_LOCAL
        daily_break_end = DEFAULT_DAILY_BREAK_END_LOCAL
        if isinstance(daily_break, dict):
            daily_break_start = str(daily_break.get("start", daily_break_start))
            daily_break_end = str(daily_break.get("end", daily_break_end))
        else:
            self._init_error = self._init_error or "daily_break_local має бути об'єктом"

        try:
            daily_break_minutes = _minutes_between(daily_break_start, daily_break_end)
        except Exception as exc:  # noqa: BLE001
            daily_break_minutes = _minutes_between(DEFAULT_DAILY_BREAK_START_LOCAL, DEFAULT_DAILY_BREAK_END_LOCAL)
            self._init_error = self._init_error or f"некоректний daily_break_local: {exc}"

        override_tag = profile.get("calendar_tag")
        tag = fallback_tag
        if isinstance(override_tag, str) and override_tag:
            tag = override_tag

        return TradingCalendar(
            closed_intervals_utc=list(closed_intervals),
            calendar_tag=str(tag),
            tz_name=str(recurrence_tz),
            weekly_open_time=str(weekly_open),
            weekly_close_time=str(weekly_close),
            daily_break_start=str(daily_break_start),
            daily_break_minutes=int(daily_break_minutes),
        )
