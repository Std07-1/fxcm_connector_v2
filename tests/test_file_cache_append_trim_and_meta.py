from __future__ import annotations

from pathlib import Path

import pytest

from store.file_cache.history_cache import FileCache


def _bar(open_ms: int, open_price: float) -> dict:
    close_ms = open_ms + 60_000 - 1
    return {
        "open_time": open_ms,
        "close_time": close_ms,
        "open": open_price,
        "high": open_price + 1.0,
        "low": open_price - 1.0,
        "close": open_price + 0.5,
        "volume": 10.0,
        "tick_count": 2,
        "complete": True,
    }


def test_file_cache_append_trim_and_meta(tmp_path: Path) -> None:
    cache = FileCache(root=tmp_path, max_bars=3, warmup_bars=0, strict=True)
    base = 1_700_000_000_000
    base -= base % 60_000
    bars = [_bar(base, 10.0), _bar(base + 60_000, 11.0), _bar(base + 120_000, 12.0)]
    result = cache.append_complete_bars(symbol="XAUUSD", tf="1m", bars=bars)
    assert result.inserted == 3
    assert result.duplicates == 0

    # Додаємо дубль open_time з іншими цінами + ще один бар для trim
    duplicate = _bar(base + 60_000, 99.0)
    extra = _bar(base + 180_000, 13.0)
    result2 = cache.append_complete_bars(symbol="XAUUSD", tf="1m", bars=[duplicate, extra])
    assert result2.duplicates == 1

    rows, meta = cache.load("XAUUSD", "1m")
    assert len(rows) == 3
    assert int(meta.get("rows", 0)) == 3
    assert int(meta.get("last_close_time_ms", 0)) == base + 180_000 + 60_000 - 1
    # Перевіряємо keep-last для дубля
    row_mid = [r for r in rows if int(r["open_time_ms"]) == base + 60_000][0]
    assert float(row_mid["open"]) == pytest.approx(99.0)
