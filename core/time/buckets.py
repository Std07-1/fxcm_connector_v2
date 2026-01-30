from __future__ import annotations

from typing import Dict

from core.time.calendar import Calendar

TF_TO_MS: Dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def floor_to_bucket_ms(ts_ms: int, tf: str) -> int:
    """Повертає початок bucket у ms для заданого TF."""
    if tf not in TF_TO_MS:
        raise ValueError("Невідомий TF для bucket: " + tf)
    size = TF_TO_MS[tf]
    return ts_ms - (ts_ms % size)


def bucket_end_ms(ts_ms: int, tf: str) -> int:
    """Повертає кінець bucket (верхня межа) у ms для заданого TF."""
    start = floor_to_bucket_ms(ts_ms, tf)
    return start + TF_TO_MS[tf]


def bucket_close_ms(ts_ms: int, tf: str) -> int:
    """Повертає close_time у ms для заданого TF."""
    return bucket_end_ms(ts_ms, tf) - 1


def get_bucket_open_ms(tf: str, ts_ms: int, calendar: Calendar | None) -> int:
    """Повертає open_time у ms для заданого TF (1d — через Calendar boundary)."""
    if tf == "1d":
        if calendar is None:
            raise ValueError("Calendar є обов'язковим для 1d boundary")
        return calendar.trading_day_boundary_for(ts_ms)
    return floor_to_bucket_ms(ts_ms, tf)


def get_bucket_close_ms(tf: str, bucket_open_ms: int, calendar: Calendar | None) -> int:
    """Повертає close_time (inclusive) у ms для заданого TF (1d — через Calendar)."""
    if tf == "1d":
        if calendar is None:
            raise ValueError("Calendar є обов'язковим для 1d boundary")
        next_boundary_ms = calendar.next_trading_day_boundary_ms(bucket_open_ms)
        return int(next_boundary_ms) - 1
    return bucket_open_ms + TF_TO_MS[tf] - 1
