from __future__ import annotations

from pathlib import Path

import pytest

from store.file_cache.history_cache import FileCache


def test_file_cache_alignment_rails(tmp_path: Path) -> None:
    cache = FileCache(root=tmp_path, max_bars=10, warmup_bars=0, strict=True)
    bad_open = {
        "open_time": 1_700_000_000_123,
        "close_time": 1_700_000_060_122,
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": 1.05,
        "volume": 10.0,
        "complete": True,
    }
    with pytest.raises(ValueError):
        cache.append_complete_bars(symbol="XAUUSD", tf="1m", bars=[bad_open])

    bad_close = {
        "open_time": 1_700_000_000_000,
        "close_time": 1_700_000_000_000,
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": 1.05,
        "volume": 10.0,
        "complete": True,
    }
    with pytest.raises(ValueError):
        cache.append_complete_bars(symbol="XAUUSD", tf="1m", bars=[bad_close])
