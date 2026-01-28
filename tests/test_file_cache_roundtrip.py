from __future__ import annotations

import csv
import json
from pathlib import Path

from store.file_cache.cache_utils import CACHE_COLUMNS, CACHE_VERSION, validate_geometry
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


def test_file_cache_roundtrip(tmp_path: Path) -> None:
    cache = HistoryCache(root=tmp_path, symbol="XAU/USD", tf="m1", max_bars=100, warmup_bars=0)
    base = 1_699_999_980_000
    bars = [_bar(base), _bar(base + 60_000)]
    result = cache.append_stream_bars(bars)
    assert result.inserted == 2
    assert result.duplicates == 0

    rows = cache.load()
    assert len(rows) == 2
    validate_geometry("1m", int(rows[0]["open_time_ms"]), int(rows[0]["close_time_ms"]))

    csv_path = tmp_path / "XAUUSD_1m.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        assert list(reader.fieldnames or []) == CACHE_COLUMNS

    meta = json.loads((tmp_path / "XAUUSD_1m.meta.json").read_text(encoding="utf-8"))
    assert int(meta.get("version", 0)) == CACHE_VERSION
    assert int(meta.get("rows", 0)) == 2
    assert int(meta.get("last_close_time_ms", 0)) > 0
