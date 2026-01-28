from __future__ import annotations

import pytest

from core.time.closed_intervals import normalize_closed_intervals_utc


def test_normalize_closed_intervals_sorts_and_allows_touching() -> None:
    base = 1_700_000_000_000
    intervals = [[base + 200, base + 300], [base + 100, base + 200], [base + 300, base + 400]]
    normalized = normalize_closed_intervals_utc(intervals)
    assert normalized == [[base + 100, base + 200], [base + 200, base + 300], [base + 300, base + 400]]


def test_normalize_closed_intervals_overlap_rejected() -> None:
    base = 1_700_000_000_000
    intervals = [[base + 100, base + 250], [base + 200, base + 300]]
    with pytest.raises(ValueError, match="overlap"):
        normalize_closed_intervals_utc(intervals)
