from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.time.closed_intervals import normalize_closed_intervals_utc
from core.time.sessions import CalendarOverrides, TradingCalendar, _to_utc_iso, load_calendar_overrides


@dataclass(init=False)
class Calendar:
    """SSOT календар з підтримкою сесій та daily break (DST-aware)."""

    calendar_tag: str
    closed_intervals_utc: List[Tuple[int, int]] = field(default_factory=list)
    overrides_path: str = "config/calendar_overrides.json"
    _calendar: TradingCalendar = field(init=False, repr=False)
    _init_error: Optional[str] = field(init=False, default=None)

    def __init__(
        self,
        closed_intervals_utc: Optional[List[Tuple[int, int]]] = None,
        calendar_tag: str = "",
        overrides_path: str = "config/calendar_overrides.json",
    ) -> None:
        self.closed_intervals_utc = list(closed_intervals_utc or [])
        self.calendar_tag = calendar_tag
        self.overrides_path = overrides_path
        self._calendar = None  # type: ignore[assignment]
        self._init_error = None
        self.__post_init__()

    def __post_init__(self) -> None:
        overrides: Optional[CalendarOverrides] = None
        try:
            overrides = load_calendar_overrides(
                repo_root=Path(__file__).resolve().parents[2],
                path=self.overrides_path,
                tag=self.calendar_tag,
            )
        except Exception as exc:  # noqa: BLE001
            self._init_error = f"calendar_overrides init_error: {exc}"

        if self.closed_intervals_utc:
            self._init_error = self._init_error or (
                "closed_intervals_utc має бути порожнім у Calendar; " "SSOT — config/calendar_overrides.json"
            )

        normalized_overrides: Optional[CalendarOverrides] = None
        if overrides is not None:
            try:
                normalized = normalize_closed_intervals_utc(list(overrides.closed_intervals_utc))
                normalized_overrides = CalendarOverrides(
                    calendar_tag=overrides.calendar_tag,
                    tz_name=overrides.tz_name,
                    weekly_open=overrides.weekly_open,
                    weekly_close=overrides.weekly_close,
                    daily_break_start=overrides.daily_break_start,
                    daily_break_minutes=overrides.daily_break_minutes,
                    closed_intervals_utc=[(int(pair[0]), int(pair[1])) for pair in normalized],
                )
            except Exception as exc:  # noqa: BLE001
                self._init_error = self._init_error or f"closed_intervals_utc невалідні: {exc}"
        overrides = normalized_overrides

        self._calendar = TradingCalendar(
            closed_intervals_utc=[],
            calendar_tag=self.calendar_tag,
            overrides=overrides,
            init_error_seed=self._init_error,
        )
        if self._calendar.init_error and not self._init_error:
            self._init_error = self._calendar.init_error

    @property
    def tc(self) -> TradingCalendar:
        return self._calendar

    def health_error(self) -> Optional[str]:
        return self._init_error or self._calendar.init_error

    def is_open(self, ts_ms: int, symbol: Optional[str] = None) -> bool:
        if self._init_error:
            return False
        return self._calendar.is_trading_time(ts_ms)

    def market_state(self, ts_ms: int, symbol: Optional[str] = None) -> Dict[str, object]:
        if self._init_error:
            safe_iso = _to_utc_iso(ts_ms)
            return {
                "is_open": False,
                "next_open_utc": safe_iso,
                "next_pause_utc": safe_iso,
                "calendar_tag": self.calendar_tag,
                "tz_backend": "init_error",
            }
        return self._calendar.market_state(ts_ms)

    def next_open_ms(self, ts_ms: int, symbol: Optional[str] = None) -> int:
        if self._init_error:
            return ts_ms
        return self._calendar.next_trading_open_ms(ts_ms)

    def next_pause_ms(self, ts_ms: int, symbol: Optional[str] = None) -> int:
        if self._init_error:
            return ts_ms
        return self._calendar.next_trading_pause_ms(ts_ms)

    def last_trading_close_ms(self, ts_ms: int, symbol: Optional[str] = None) -> int:
        if self._init_error:
            return ts_ms
        if self.is_open(ts_ms, symbol=symbol):
            return int(self._calendar.next_trading_pause_ms(ts_ms)) - 1
        dt_utc = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        dt_local = dt_utc.astimezone(self._calendar._tz)
        for day_offset in range(0, 8):
            day = dt_local.date() - timedelta(days=day_offset)
            intervals = self._calendar._open_intervals_for_date(day)
            if not intervals:
                continue
            if day_offset == 0:
                ends = [end for _start, end in intervals if end <= dt_local]
                if not ends:
                    continue
                end_dt = max(ends)
            else:
                end_dt = max(end for _start, end in intervals)
            return int(end_dt.astimezone(timezone.utc).timestamp() * 1000) - 1
        return ts_ms

    def explain(self, ts_ms: int, symbol: Optional[str] = None) -> List[str]:
        if self._init_error:
            return ["calendar_error"]
        return self._calendar.explain(ts_ms)

    def is_repair_window(self, now_ms: int, safe_only_when_market_closed: bool) -> bool:
        """Дозволяє repair лише у дозволеному вікні."""
        if not safe_only_when_market_closed:
            return True
        return not self.is_open(now_ms)

    def trading_day_boundary_for(self, ts_ms: int) -> int:
        if self._init_error:
            return ts_ms
        dt_utc = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        dt_local = dt_utc.astimezone(self._calendar._tz)
        boundary_local = datetime.combine(dt_local.date(), self._calendar._break_start, tzinfo=self._calendar._tz)
        if dt_local < boundary_local:
            boundary_local = boundary_local - timedelta(days=1)
        return int(boundary_local.astimezone(timezone.utc).timestamp() * 1000)

    def next_trading_day_boundary_ms(self, ts_ms: int) -> int:
        if self._init_error:
            return ts_ms
        dt_utc = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        dt_local = dt_utc.astimezone(self._calendar._tz)
        boundary_local = datetime.combine(dt_local.date(), self._calendar._break_start, tzinfo=self._calendar._tz)
        if dt_local >= boundary_local:
            boundary_local = boundary_local + timedelta(days=1)
        return int(boundary_local.astimezone(timezone.utc).timestamp() * 1000)
