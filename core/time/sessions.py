from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date, datetime, time, timedelta, timezone, tzinfo
from typing import List, Optional, Tuple

from dateutil import tz as _tz

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


def _parse_hhmm(value: str) -> time:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("час має формат HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("час має коректні межі")
    return time(hour=hour, minute=minute)


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
    _tz: tzinfo = field(init=False)
    _init_error: Optional[str] = field(init=False, default=None)
    _tz_backend: str = field(init=False, default="unknown")
    _weekly_open: time = field(init=False)
    _weekly_close: time = field(init=False)
    _break_start: time = field(init=False)

    def __post_init__(self) -> None:
        try:
            self._weekly_open = _parse_hhmm(self.weekly_open_time)
            self._weekly_close = _parse_hhmm(self.weekly_close_time)
            self._break_start = _parse_hhmm(self.daily_break_start)
        except Exception as exc:  # noqa: BLE001
            self._weekly_open = time(0, 0)
            self._weekly_close = time(0, 0)
            self._break_start = time(0, 0)
            self._init_error = f"помилка парсингу часу календаря: {exc}"

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
