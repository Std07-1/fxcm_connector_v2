from __future__ import annotations

from datetime import datetime, timezone

from _pytest.monkeypatch import MonkeyPatch

from core.time import sessions
from core.time.timestamps import to_epoch_ms_utc


def _ms(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> int:
    return to_epoch_ms_utc(datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc))


def test_tz_backend_dateutil_no_error(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(sessions, "ZoneInfo", None)
    calendar = sessions.TradingCalendar([], "fxcm_calendar_v1_ny", tz_name="America/New_York")
    assert calendar.init_error is None
    state = calendar.market_state(_ms(2026, 1, 20, 12, 0, 0))
    assert state["tz_backend"] == "dateutil"


def test_tz_backend_unknown_on_fail(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(sessions, "ZoneInfo", None)
    monkeypatch.setattr(sessions._tz, "gettz", lambda _: None)
    calendar = sessions.TradingCalendar([], "fxcm_calendar_v1_ny", tz_name="No/SuchTZ")
    assert calendar.init_error is not None
    state = calendar.market_state(_ms(2026, 1, 20, 12, 0, 0))
    assert state["tz_backend"] == "unknown"
