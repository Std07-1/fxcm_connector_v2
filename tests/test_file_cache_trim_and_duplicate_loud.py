from __future__ import annotations

from pathlib import Path

from store.file_cache.history_cache import HistoryCache


def _bar(open_ms: int) -> dict:
    close_ms = open_ms + 60_000 - 1
    return {
        "open_time": open_ms,
        "close_time": close_ms,
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": 1.05,
        "volume": 10.0,
        "complete": True,
        "synthetic": False,
        "source": "stream",
        "event_ts": close_ms,
    }


def test_file_cache_trim_and_duplicate_loud(tmp_path: Path) -> None:
    cache = HistoryCache(root=tmp_path, symbol="XAUUSD", tf="1m", max_bars=2, warmup_bars=0)
    base = 1_699_999_980_000
    bars = [
        _bar(base),
        _bar(base + 60_000),
        _bar(base + 60_000),  # duplicate
        _bar(base + 120_000),
    ]
    result = cache.append_stream_bars(bars)
    assert result.duplicates == 1
    assert result.trimmed == 1

    rows = cache.load()
    assert len(rows) == 2
    assert int(rows[0]["open_time_ms"]) == base + 60_000
    assert int(rows[1]["open_time_ms"]) == base + 120_000
