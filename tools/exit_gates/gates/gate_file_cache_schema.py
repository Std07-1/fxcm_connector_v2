from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Tuple

from store.file_cache.cache_utils import CACHE_COLUMNS, CACHE_VERSION, validate_geometry
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
        "complete": True,
        "source": "stream_close",
    }


def _read_csv(path: Path) -> Tuple[List[str], List[Dict[str, Any]]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return fieldnames, rows


def run() -> Tuple[bool, str]:
    with TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        cache = FileCache(root=root, max_bars=100, warmup_bars=0, strict=True)
        base = 1_699_999_980_000
        bars = [
            _build_bar(base),
            _build_bar(base + 60_000),
            _build_bar(base + 120_000),
        ]
        cache.append_complete_bars(symbol="XAU/USD", tf="1m", bars=bars)

        csv_path = root / "XAUUSD_1m.csv"
        meta_path = root / "XAUUSD_1m.meta.json"
        if not csv_path.exists() or not meta_path.exists():
            return False, "FAIL: cache файли не створені"

        fieldnames, rows = _read_csv(csv_path)
        if fieldnames != CACHE_COLUMNS:
            return False, "FAIL: CACHE_COLUMNS не відповідає CSV header"
        if len(rows) != 3:
            return False, "FAIL: rows != 3"

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if int(meta.get("version", 0)) != CACHE_VERSION:
            return False, "FAIL: meta.version"
        if int(meta.get("rows", 0)) != 3:
            return False, "FAIL: meta.rows"
        if int(meta.get("last_close_time_ms", 0)) <= 0:
            return False, "FAIL: meta.last_close_time_ms"

        prev_open = 0
        for row in rows:
            open_ms = int(row.get("open_time_ms", 0))
            close_ms = int(row.get("close_time_ms", 0))
            validate_geometry("1m", open_ms, close_ms)
            if open_ms <= prev_open:
                return False, "FAIL: rows не відсортовані/UNIQUE"
            prev_open = open_ms

    return True, "OK: file cache schema"


if __name__ == "__main__":
    fail_direct_gate_run("gate_file_cache_schema")
