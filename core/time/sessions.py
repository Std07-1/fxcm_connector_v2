from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date as _date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

from dateutil import tz as _tz

from core.time.closed_intervals import normalize_closed_intervals_utc

try:
    from zoneinfo import ZoneInfo  # type: ignore
except Exception:  # noqa: BLE001
    try:
        from backports.zoneinfo import ZoneInfo  # type: ignore
    except Exception:  # noqa: BLE001
        ZoneInfo = None


DEFAULT_TZ_NAME = "America/New_York"
DEFAULT_WEEKLY_OPEN = "17:00"
DEFAULT_WEEKLY_CLOSE = "17:00"
DEFAULT_DAILY_BREAK_START = "17:00"
DEFAULT_DAILY_BREAK_MINUTES = 5


def _parse_hhmm(value: str) -> Tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("час має формат HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("час має коректні межі")
    return hour, minute


def _time_from_hhmm(value: str) -> time:
    hour, minute = _parse_hhmm(value)
    return time(hour=hour, minute=minute)


def _minutes_between(start_hhmm: str, end_hhmm: str) -> int:
    start_h, start_m = _parse_hhmm(start_hhmm)
    end_h, end_m = _parse_hhmm(end_hhmm)
    start_total = start_h * 60 + start_m
    end_total = end_h * 60 + end_m
    if end_total <= start_total:
        raise ValueError("кінець daily break має бути після початку")
    return end_total - start_total


def _resolve_tz_or_raise(tz_name: str) -> tzinfo:
    if tz_name.upper() == "UTC" or tz_name == "Etc/UTC":
        return timezone.utc
    if ZoneInfo is not None:
        try:
            return cast(tzinfo, ZoneInfo(tz_name))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"TZ не резолвиться: {tz_name}: {exc}") from exc
    fallback = _tz.gettz(tz_name)
    if fallback is None:
        raise ValueError(f"TZ не резолвиться: {tz_name}")
    return cast(tzinfo, fallback)


@dataclass(frozen=True)
class CalendarOverrides:
    calendar_tag: str
    tz_name: str
    weekly_open: str
    weekly_close: str
    daily_break_start: str
    daily_break_minutes: int
    closed_intervals_utc: List[Tuple[int, int]]


def load_calendar_overrides(
    repo_root: Path,
    path: str = "config/calendar_overrides.json",
    tag: str = "",
) -> CalendarOverrides:
    overrides_path = repo_root / path
    if not overrides_path.exists():
        raise ValueError(f"calendar_overrides.json не знайдено: {overrides_path}")
    try:
        data = json.loads(overrides_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"calendar_overrides.json невалідний JSON: {exc}") from exc

    if not tag:
        raise ValueError("calendar_tag має бути заданий")
    if not isinstance(data, list):
        raise ValueError("calendar_overrides.json має містити список профілів")
    entry: Optional[Dict[str, Any]] = None
    for item in data:
        if isinstance(item, dict) and item.get("calendar_tag") == tag:
            entry = dict(item)
            break

    if entry is None:
        raise ValueError(f"calendar_tag не знайдено: {tag}")

    entry_tag = entry.get("calendar_tag")
    if not isinstance(entry_tag, str) or not entry_tag:
        raise ValueError("calendar_tag має бути непорожнім рядком")
    if tag and entry_tag != tag:
        raise ValueError(f"calendar_tag не збігається: очікував {tag}, отримав {entry_tag}")

    tz_name = entry.get("tz_name") or entry.get("recurrence_tz")
    if not isinstance(tz_name, str) or not tz_name:
        raise ValueError("tz_name має бути непорожнім рядком")

    weekly_open = entry.get("weekly_open") or entry.get("weekly_open_local")
    weekly_close = entry.get("weekly_close") or entry.get("weekly_close_local")
    if not isinstance(weekly_open, str) or not isinstance(weekly_close, str):
        raise ValueError("weekly_open/weekly_close мають бути рядками HH:MM")

    daily_break_start = entry.get("daily_break_start")
    daily_break_minutes = entry.get("daily_break_minutes")
    if daily_break_start is None:
        daily_break_local = entry.get("daily_break_local")
        if isinstance(daily_break_local, dict):
            daily_break_start = daily_break_local.get("start")
            daily_break_end = daily_break_local.get("end")
            if isinstance(daily_break_start, str) and isinstance(daily_break_end, str):
                daily_break_minutes = _minutes_between(daily_break_start, daily_break_end)
        elif daily_break_local is not None:
            raise ValueError("daily_break_local має бути об'єктом")
    if not isinstance(daily_break_start, str):
        raise ValueError("daily_break_start має бути рядком HH:MM")
    if not isinstance(daily_break_minutes, int) or isinstance(daily_break_minutes, bool):
        raise ValueError("daily_break_minutes має бути int")
    if daily_break_minutes <= 0:
        raise ValueError("daily_break_minutes має бути > 0")

    _parse_hhmm(weekly_open)
    _parse_hhmm(weekly_close)
    _parse_hhmm(daily_break_start)
    _resolve_tz_or_raise(tz_name)

    raw_intervals = entry.get("closed_intervals_utc", [])
    normalized = normalize_closed_intervals_utc(list(raw_intervals) if raw_intervals is not None else [])
    closed_intervals = [(int(pair[0]), int(pair[1])) for pair in normalized]

    return CalendarOverrides(
        calendar_tag=entry_tag,
        tz_name=tz_name,
        weekly_open=weekly_open,
        weekly_close=weekly_close,
        daily_break_start=daily_break_start,
        daily_break_minutes=int(daily_break_minutes),
        closed_intervals_utc=closed_intervals,
    )


def _to_utc_iso(ts_ms: int) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dt_to_ms(dt: datetime) -> int:
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


@dataclass
class TradingCalendar:
    """SSOT календар сесій (DST-aware, weekly open/close + daily break)."""

    closed_intervals_utc: List[Tuple[int, int]]
    calendar_tag: str
    tz_name: str = DEFAULT_TZ_NAME
    weekly_open_time: str = DEFAULT_WEEKLY_OPEN
    weekly_close_time: str = DEFAULT_WEEKLY_CLOSE
    daily_break_start: str = DEFAULT_DAILY_BREAK_START
    daily_break_minutes: int = DEFAULT_DAILY_BREAK_MINUTES
    overrides: Optional[CalendarOverrides] = None
    init_error_seed: Optional[str] = field(default=None, repr=False)
    _tz: tzinfo = field(init=False)
    _init_error: Optional[str] = field(init=False, default=None)
    _tz_backend: str = field(init=False, default="unknown")
    _weekly_open: time = field(init=False)
    _weekly_close: time = field(init=False)
    _break_start: time = field(init=False)

    def __post_init__(self) -> None:
        self._init_error = self.init_error_seed
        if self.overrides is not None:
            self.calendar_tag = self.overrides.calendar_tag
            self.tz_name = self.overrides.tz_name
            self.weekly_open_time = self.overrides.weekly_open
            self.weekly_close_time = self.overrides.weekly_close
            self.daily_break_start = self.overrides.daily_break_start
            self.daily_break_minutes = int(self.overrides.daily_break_minutes)
            merged: List[Tuple[int, int]] = []
            seen = set()
            for interval in list(self.overrides.closed_intervals_utc) + list(self.closed_intervals_utc):
                if interval not in seen:
                    seen.add(interval)
                    merged.append(interval)
            self.closed_intervals_utc = merged
        if self.daily_break_minutes <= 0:
            self._init_error = self._init_error or "daily_break_minutes має бути > 0"
        try:
            self._weekly_open = _time_from_hhmm(self.weekly_open_time)
            self._weekly_close = _time_from_hhmm(self.weekly_close_time)
            self._break_start = _time_from_hhmm(self.daily_break_start)
        except Exception as exc:  # noqa: BLE001
            self._weekly_open = time(0, 0)
            self._weekly_close = time(0, 0)
            self._break_start = time(0, 0)
            self._init_error = self._init_error or f"помилка парсингу часу календаря: {exc}"

        if self.tz_name.upper() == "UTC" or self.tz_name == "Etc/UTC":
            self._tz = timezone.utc
            self._tz_backend = "utc"
            return

        if ZoneInfo is None:
            fallback = _tz.gettz(self.tz_name)
            if fallback is None:
                self._tz = timezone.utc
                self._tz_backend = "unknown"
                self._init_error = (
                    self._init_error or "TZ не резолвиться: zoneinfo недоступний, dateutil.tz не знайшов tzdata"
                )
                return
            self._tz = fallback
            self._tz_backend = "dateutil"
            return
        try:
            self._tz = ZoneInfo(self.tz_name)
            self._tz_backend = "zoneinfo"
        except Exception as exc:  # noqa: BLE001
            fallback = _tz.gettz(self.tz_name)
            if fallback is None:
                self._tz = timezone.utc
                self._tz_backend = "unknown"
                self._init_error = (
                    "TZ не резолвиться: zoneinfo/dateutil не змогли ініціалізувати " f"{self.tz_name}: {exc}"
                )
                return
            self._tz = fallback
            self._tz_backend = "dateutil"

    @property
    def init_error(self) -> Optional[str]:
        return self._init_error

    @property
    def tz_backend(self) -> str:
        return self._tz_backend

    def explain(self, ts_ms: int) -> List[str]:
        reasons: List[str] = []
        if self._init_error:
            reasons.append("calendar_error")
            return reasons
        if self._is_closed_interval(ts_ms):
            reasons.append("closed_interval")
        dt_local = self._to_local(ts_ms)
        weekday = dt_local.weekday()
        t = dt_local.time()
        if weekday == 5:
            reasons.append("weekend_closed")
        if weekday == 6 and t < self._weekly_open:
            reasons.append("weekend_closed")
        if weekday == 4 and t >= self._weekly_close:
            reasons.append("weekend_closed")
        if weekday in {0, 1, 2, 3}:
            end = (
                datetime.combine(dt_local.date(), self._break_start, tzinfo=self._tz)
                + timedelta(minutes=self.daily_break_minutes)
            ).time()
            if self._break_start <= t < end:
                reasons.append("daily_break")
        return reasons

    def is_trading_time(self, ts_ms: int) -> bool:
        if self._init_error:
            return False
        if self._is_closed_interval(ts_ms):
            return False
        dt_local = self._to_local(ts_ms)
        weekday = dt_local.weekday()
        t = dt_local.time()
        if weekday == 5:
            return False
        if weekday == 6 and t < self._weekly_open:
            return False
        if weekday == 4 and t >= self._weekly_close:
            return False
        if weekday in {0, 1, 2, 3}:
            break_end = datetime.combine(dt_local.date(), self._break_start, tzinfo=self._tz) + timedelta(
                minutes=self.daily_break_minutes
            )
            if self._break_start <= t < break_end.time():
                return False
        return True

    def next_trading_open_ms(self, ts_ms: int) -> int:
        if self._is_closed_interval(ts_ms):
            end_ms = self._closed_interval_end(ts_ms)
            if end_ms is not None:
                ts_ms = end_ms + 1
        dt_local = self._to_local(ts_ms)
        for day_offset in range(0, 8):
            day = dt_local.date() + timedelta(days=day_offset)
            intervals = self._open_intervals_for_date(day)
            for start, end in intervals:
                if day_offset == 0 and start <= dt_local < end:
                    continue
                if day_offset == 0 and dt_local >= end:
                    continue
                if day_offset == 0 and dt_local > start:
                    continue
                candidate_ms = _dt_to_ms(start)
                if self._is_closed_interval(candidate_ms):
                    end_ms = self._closed_interval_end(candidate_ms)
                    if end_ms is not None:
                        return self.next_trading_open_ms(end_ms + 1)
                return candidate_ms
        return ts_ms

    def next_trading_pause_ms(self, ts_ms: int) -> int:
        dt_local = self._to_local(ts_ms)
        intervals = self._open_intervals_for_date(dt_local.date())
        for start, end in intervals:
            if start <= dt_local < end:
                pause_ms = _dt_to_ms(end)
                closed_start = self._next_closed_start(ts_ms, pause_ms)
                if closed_start is not None:
                    return closed_start
                return pause_ms
        next_open = self.next_trading_open_ms(ts_ms)
        dt_open = self._to_local(next_open)
        intervals = self._open_intervals_for_date(dt_open.date())
        for start, end in intervals:
            if start <= dt_open < end:
                return _dt_to_ms(end)
        return next_open

    def market_state(self, ts_ms: int) -> dict:
        is_open = self.is_trading_time(ts_ms)
        next_open = self.next_trading_open_ms(ts_ms)
        next_pause = self.next_trading_pause_ms(ts_ms)
        return {
            "is_open": is_open,
            "next_open_utc": _to_utc_iso(next_open),
            "next_pause_utc": _to_utc_iso(next_pause),
            "calendar_tag": self.calendar_tag,
            "tz_backend": self.tz_backend,
        }

    def _to_local(self, ts_ms: int) -> datetime:
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        return dt.astimezone(self._tz)

    def _is_closed_interval(self, ts_ms: int) -> bool:
        for start_ms, end_ms in self.closed_intervals_utc:
            if start_ms <= ts_ms < end_ms:
                return True
        return False

    def _closed_interval_end(self, ts_ms: int) -> Optional[int]:
        for start_ms, end_ms in self.closed_intervals_utc:
            if start_ms <= ts_ms < end_ms:
                return int(end_ms)
        return None

    def _next_closed_start(self, ts_ms: int, limit_ms: int) -> Optional[int]:
        starts = [start for start, end in self.closed_intervals_utc if ts_ms < start < limit_ms]
        if not starts:
            return None
        return int(min(starts))

    def _open_intervals_for_date(self, day: _date) -> List[Tuple[datetime, datetime]]:
        weekday = day.weekday()
        day_start = datetime.combine(day, time(0, 0), tzinfo=self._tz)
        day_end = day_start + timedelta(days=1)
        if weekday == 5:
            return []
        if weekday == 6:
            start = datetime.combine(day, self._weekly_open, tzinfo=self._tz)
            return [(start, day_end)] if start < day_end else []
        if weekday == 4:
            end = datetime.combine(day, self._weekly_close, tzinfo=self._tz)
            return [(day_start, end)] if day_start < end else []
        break_start_dt = datetime.combine(day, self._break_start, tzinfo=self._tz)
        break_end_dt = break_start_dt + timedelta(minutes=self.daily_break_minutes)
        intervals: List[Tuple[datetime, datetime]] = []
        if day_start < break_start_dt:
            intervals.append((day_start, break_start_dt))
        if break_end_dt < day_end:
            intervals.append((break_end_dt, day_end))
        return intervals
