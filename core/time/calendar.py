from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.time.sessions import CalendarOverrides, TradingCalendar, load_calendar_overrides


@dataclass
class Calendar:
    """SSOT календар з підтримкою сесій та daily break (DST-aware)."""

    closed_intervals_utc: List[Tuple[int, int]]
    calendar_tag: str
    _calendar: TradingCalendar = field(init=False, repr=False)
    _init_error: Optional[str] = field(init=False, default=None)

    def __post_init__(self) -> None:
        overrides: Optional[CalendarOverrides] = None
        try:
            overrides = load_calendar_overrides(
                repo_root=Path(__file__).resolve().parents[2],
                tag=self.calendar_tag,
            )
        except Exception as exc:  # noqa: BLE001
            self._init_error = f"calendar_overrides init_error: {exc}"

        self._calendar = TradingCalendar(
            closed_intervals_utc=list(self.closed_intervals_utc),
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
        return self._calendar.is_trading_time(ts_ms)

    def market_state(self, ts_ms: int, symbol: Optional[str] = None) -> Dict[str, object]:
        return self._calendar.market_state(ts_ms)

    def next_open_ms(self, ts_ms: int, symbol: Optional[str] = None) -> int:
        return self._calendar.next_trading_open_ms(ts_ms)

    def next_pause_ms(self, ts_ms: int, symbol: Optional[str] = None) -> int:
        return self._calendar.next_trading_pause_ms(ts_ms)

    def explain(self, ts_ms: int, symbol: Optional[str] = None) -> List[str]:
        return self._calendar.explain(ts_ms)

    def is_repair_window(self, now_ms: int, safe_only_when_market_closed: bool) -> bool:
        """Дозволяє repair лише у дозволеному вікні."""
        if not safe_only_when_market_closed:
            return True
        return not self.is_open(now_ms)
