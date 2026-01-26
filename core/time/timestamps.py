from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.validation.validator import ContractError

MIN_EPOCH_MS = 1_000_000_000_000
MAX_EPOCH_MS = 9_999_999_999_999


def to_epoch_ms_utc(dt_or_ts: Any) -> int:
    """Конвертує значення у epoch ms (UTC)."""
    if isinstance(dt_or_ts, datetime):
        if dt_or_ts.tzinfo is None:
            dt_or_ts = dt_or_ts.replace(tzinfo=timezone.utc)
        ts_ms = int(dt_or_ts.timestamp() * 1000)
    elif isinstance(dt_or_ts, int):
        ts_ms = int(dt_or_ts)
    elif isinstance(dt_or_ts, float):
        raise ContractError("timestamp має бути int ms, не float")
    else:
        raise ContractError("timestamp має бути datetime або int ms")
    if ts_ms < MIN_EPOCH_MS:
        raise ContractError("timestamp має бути epoch ms (>=1e12)")
    if ts_ms > MAX_EPOCH_MS:
        raise ContractError("timestamp має бути epoch ms (не microseconds)")
    return ts_ms
