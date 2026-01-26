from __future__ import annotations

from datetime import datetime, timezone
from typing import Tuple

from config.config import Config
from core.time.buckets import get_bucket_close_ms, get_bucket_open_ms
from runtime.preview_builder import OhlcvCache, PreviewBuilder


def _utc_ms(year: int, month: int, day: int, hour: int, minute: int, second: int) -> int:
    dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _assert_eq(actual: int, expected: int, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label}: очікувалось {expected}, отримано {actual}")


def run() -> Tuple[bool, str]:
    try:
        config_1d = Config(trading_day_boundary_utc="22:00", ohlcv_preview_tfs=["1d"], ohlcv_preview_enabled=True)
        cache_1d = OhlcvCache()
        builder_1d = PreviewBuilder(config=config_1d, cache=cache_1d)

        boundary_ms = _utc_ms(2026, 1, 2, 22, 0, 0)
        ts_before = boundary_ms - 1_000
        ts_after = boundary_ms + 1_000

        builder_1d.on_tick(symbol="XAUUSD", mid=2000.0, tick_ts_ms=ts_before)
        builder_1d.on_tick(symbol="XAUUSD", mid=2000.5, tick_ts_ms=ts_after)

        bars_1d = cache_1d.get_tail("XAUUSD", "1d", 2)
        if len(bars_1d) != 2:
            return False, "FAIL: очікувалось 2 1d bars у preview"

        expected_open_before = get_bucket_open_ms("1d", ts_before, config_1d.trading_day_boundary_utc)
        expected_close_before = get_bucket_close_ms("1d", expected_open_before, config_1d.trading_day_boundary_utc)
        expected_open_after = get_bucket_open_ms("1d", ts_after, config_1d.trading_day_boundary_utc)
        expected_close_after = get_bucket_close_ms("1d", expected_open_after, config_1d.trading_day_boundary_utc)

        _assert_eq(int(bars_1d[0]["open_time"]), expected_open_before, "1d open_time до boundary")
        _assert_eq(int(bars_1d[0]["close_time"]), expected_close_before, "1d close_time до boundary")
        _assert_eq(int(bars_1d[1]["open_time"]), expected_open_after, "1d open_time після boundary")
        _assert_eq(int(bars_1d[1]["close_time"]), expected_close_after, "1d close_time після boundary")

        config_15m = Config(ohlcv_preview_tfs=["15m"], ohlcv_preview_enabled=True)
        cache_15m = OhlcvCache()
        builder_15m = PreviewBuilder(config=config_15m, cache=cache_15m)

        ts_mid = _utc_ms(2026, 1, 2, 12, 7, 30)
        builder_15m.on_tick(symbol="XAUUSD", mid=1999.0, tick_ts_ms=ts_mid)
        bars_15m = cache_15m.get_tail("XAUUSD", "15m", 1)
        if len(bars_15m) != 1:
            return False, "FAIL: очікувалось 1 15m bar у preview"

        expected_open_15m = get_bucket_open_ms("15m", ts_mid, config_15m.trading_day_boundary_utc)
        expected_close_15m = get_bucket_close_ms("15m", expected_open_15m, config_15m.trading_day_boundary_utc)

        _assert_eq(int(bars_15m[0]["open_time"]), expected_open_15m, "15m open_time")
        _assert_eq(int(bars_15m[0]["close_time"]), expected_close_15m, "15m close_time")
    except Exception as exc:  # noqa: BLE001
        return False, f"FAIL: {exc}"

    return True, "OK: preview bucket boundaries (1d, 15m) узгоджені з SSOT buckets"
