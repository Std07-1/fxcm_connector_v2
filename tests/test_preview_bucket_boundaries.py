from __future__ import annotations

from datetime import datetime, timezone

from config.config import Config
from core.time.buckets import get_bucket_close_ms, get_bucket_open_ms
from core.time.calendar import Calendar
from runtime.preview_builder import OhlcvCache, PreviewBuilder


def _utc_ms(year: int, month: int, day: int, hour: int, minute: int, second: int) -> int:
    dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def test_preview_bucket_1d_boundary() -> None:
    config = Config(ohlcv_preview_tfs=["1d"], ohlcv_preview_enabled=True)
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    cache = OhlcvCache()
    builder = PreviewBuilder(config=config, cache=cache, calendar=calendar)

    boundary_ms = _utc_ms(2026, 1, 2, 22, 0, 0)
    ts_before = boundary_ms - 1_000
    ts_after = boundary_ms + 1_000

    builder.on_tick(symbol="XAUUSD", mid=2000.0, tick_ts_ms=ts_before)
    builder.on_tick(symbol="XAUUSD", mid=2000.5, tick_ts_ms=ts_after)

    bars = cache.get_tail("XAUUSD", "1d", 2)
    assert len(bars) == 2

    expected_open_before = get_bucket_open_ms("1d", ts_before, calendar)
    expected_close_before = get_bucket_close_ms("1d", expected_open_before, calendar)
    expected_open_after = get_bucket_open_ms("1d", ts_after, calendar)
    expected_close_after = get_bucket_close_ms("1d", expected_open_after, calendar)

    assert bars[0]["open_time"] == expected_open_before
    assert bars[0]["close_time"] == expected_close_before
    assert bars[1]["open_time"] == expected_open_after
    assert bars[1]["close_time"] == expected_close_after


def test_preview_bucket_15m_boundary() -> None:
    config = Config(ohlcv_preview_tfs=["15m"], ohlcv_preview_enabled=True)
    cache = OhlcvCache()
    builder = PreviewBuilder(config=config, cache=cache)

    ts_ms = _utc_ms(2026, 1, 2, 12, 7, 30)
    builder.on_tick(symbol="XAUUSD", mid=1999.0, tick_ts_ms=ts_ms)

    bars = cache.get_tail("XAUUSD", "15m", 1)
    assert len(bars) == 1

    expected_open = get_bucket_open_ms("15m", ts_ms, None)
    expected_close = get_bucket_close_ms("15m", expected_open, None)

    assert bars[0]["open_time"] == expected_open
    assert bars[0]["close_time"] == expected_close
