from __future__ import annotations

from typing import Dict, Tuple

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


def _parse_boundary_utc(boundary: str) -> Tuple[int, int]:
    parts = boundary.split(":")
    if len(parts) != 2:
        raise ValueError("trading_day_boundary_utc має формат HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("trading_day_boundary_utc має коректний час")
    return hour, minute


def trading_day_boundary_offset_ms(trading_day_boundary_utc: str) -> int:
    """Повертає зсув boundary відносно UTC midnight у ms."""
    hour, minute = _parse_boundary_utc(trading_day_boundary_utc)
    return (hour * 60 + minute) * 60 * 1000


def _floor_to_trading_day(ts_ms: int, trading_day_boundary_utc: str) -> int:
    offset = trading_day_boundary_offset_ms(trading_day_boundary_utc)
    adjusted = ts_ms - offset
    day_start = adjusted - (adjusted % TF_TO_MS["1d"])
    return day_start + offset


def bucket_end_ms(ts_ms: int, tf: str) -> int:
    """Повертає кінець bucket (верхня межа) у ms для заданого TF."""
    start = floor_to_bucket_ms(ts_ms, tf)
    return start + TF_TO_MS[tf]


def bucket_close_ms(ts_ms: int, tf: str) -> int:
    """Повертає close_time у ms для заданого TF."""
    return bucket_end_ms(ts_ms, tf) - 1


def get_bucket_open_ms(tf: str, ts_ms: int, trading_day_boundary_utc: str) -> int:
    """Повертає open_time у ms для заданого TF з урахуванням boundary."""
    if tf == "1d":
        return _floor_to_trading_day(ts_ms, trading_day_boundary_utc)
    return floor_to_bucket_ms(ts_ms, tf)


def get_bucket_close_ms(tf: str, bucket_open_ms: int, trading_day_boundary_utc: str) -> int:
    """Повертає close_time (inclusive) у ms для заданого TF (boundary-aware)."""
    _ = trading_day_boundary_utc
    return bucket_open_ms + TF_TO_MS[tf] - 1
