from __future__ import annotations

from typing import List, Sequence, Tuple

from core.time.timestamps import MAX_EPOCH_MS, MIN_EPOCH_MS


def normalize_closed_intervals_utc(intervals: List[Sequence[int]]) -> List[Tuple[int, int]]:
    if not isinstance(intervals, list):
        raise ValueError("closed_intervals_utc має бути списком")
    normalized: List[Tuple[int, int]] = []
    for idx, interval in enumerate(intervals):
        if not isinstance(interval, (list, tuple)):
            raise ValueError(f"closed_intervals_utc[{idx}] має бути списком або кортежем")
        if len(interval) != 2:
            raise ValueError(f"closed_intervals_utc[{idx}] має містити 2 значення")
        start_ms, end_ms = interval[0], interval[1]
        if not isinstance(start_ms, int) or isinstance(start_ms, bool):
            raise ValueError(f"closed_intervals_utc[{idx}][0] має бути int")
        if not isinstance(end_ms, int) or isinstance(end_ms, bool):
            raise ValueError(f"closed_intervals_utc[{idx}][1] має бути int")
        if start_ms < MIN_EPOCH_MS or start_ms > MAX_EPOCH_MS:
            raise ValueError(f"closed_intervals_utc[{idx}][0] поза межами epoch rails: {start_ms}")
        if end_ms < MIN_EPOCH_MS or end_ms > MAX_EPOCH_MS:
            raise ValueError(f"closed_intervals_utc[{idx}][1] поза межами epoch rails: {end_ms}")
        if start_ms >= end_ms:
            raise ValueError(f"closed_intervals_utc[{idx}] має start_ms < end_ms, отримано {start_ms} >= {end_ms}")
        normalized.append((int(start_ms), int(end_ms)))

    normalized.sort(key=lambda pair: pair[0])
    for idx in range(1, len(normalized)):
        prev = normalized[idx - 1]
        cur = normalized[idx]
        if cur[0] < prev[1]:
            raise ValueError("closed_intervals_utc має overlap: " f"prev={prev[0]}..{prev[1]} cur={cur[0]}..{cur[1]}")
    return normalized
