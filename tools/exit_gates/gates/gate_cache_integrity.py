from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Tuple

from core.time.buckets import TF_TO_MS
from store.file_cache.cache_utils import CACHE_VERSION, validate_geometry
from store.file_cache.history_cache import FileCache
from tools.run_exit_gates import fail_direct_gate_run


def _build_bar(open_ms: int) -> Dict[str, Any]:
    close_ms = open_ms + 60_000 - 1
    return {
        "open_time": open_ms,
        "close_time": close_ms,
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": 1.05,
        "volume": 10.0,
        "tick_count": 3,
        "complete": True,
    }


def _assert_sorted_unique(rows: List[Dict[str, Any]]) -> None:
    last_open = None
    seen = set()
    for row in rows:
        open_ms = int(row["open_time_ms"])
        if open_ms in seen:
            raise ValueError("UNIQUE(open_time_ms) порушено")
        if last_open is not None and open_ms < last_open:
            raise ValueError("rows не відсортовані")
        seen.add(open_ms)
        last_open = open_ms


def run() -> Tuple[bool, str]:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        cache = FileCache(root=root, max_bars=5, warmup_bars=0, strict=True)
        base = 1_700_000_000_000
        base -= base % 60_000
        bars = [
            _build_bar(base),
            _build_bar(base + 60_000),
            _build_bar(base + 120_000),
        ]
        cache.append_complete_bars(symbol="XAUUSD", tf="1m", bars=bars)
        rows, meta = cache.load("XAUUSD", "1m")
        if not rows:
            return False, "FAIL: cache rows порожні"
        _assert_sorted_unique(rows)
        for row in rows:
            validate_geometry("1m", int(row["open_time_ms"]), int(row["close_time_ms"]))
        last_close = max(int(r["close_time_ms"]) for r in rows)
        if int(meta.get("version", 0)) != CACHE_VERSION:
            return False, "FAIL: meta.version"
        if int(meta.get("rows", 0)) != len(rows):
            return False, "FAIL: meta.rows"
        if int(meta.get("last_close_time_ms", 0)) != last_close:
            return False, "FAIL: meta.last_close_time_ms"
        if TF_TO_MS.get("1m") != 60_000:
            return False, "FAIL: tf_ms очікування"
    return True, "OK: cache integrity"


if __name__ == "__main__":
    fail_direct_gate_run("gate_cache_integrity")
