from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Tuple

from store.live_archive_store import SqliteLiveArchiveStore


def run() -> Tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "live_archive.sqlite"
        store = SqliteLiveArchiveStore(db_path=db_path)
        store.init_schema()
        open_ms = 1_700_000_000_000
        open_ms = open_ms - (open_ms % 60_000)
        payload = {
            "open_time": open_ms,
            "close_time": open_ms + 60_000 - 1,
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
            "complete": False,
            "synthetic": False,
            "source": "stream",
        }
        result = store.insert_bar(
            symbol="XAUUSD",
            tf="1m",
            open_time_ms=int(payload["open_time"]),
            close_time_ms=int(payload["close_time"]),
            payload=payload,
        )
        if result.status != "INSERTED":
            return False, f"FAIL: insert expected INSERTED, got {result.status}"
        dup = store.insert_bar(
            symbol="XAUUSD",
            tf="1m",
            open_time_ms=int(payload["open_time"]),
            close_time_ms=int(payload["close_time"]),
            payload=payload,
        )
        if dup.status != "DUPLICATE":
            return False, f"FAIL: duplicate expected DUPLICATE, got {dup.status}"
    return True, "OK: live_archive sqlite gate"


if __name__ == "__main__":
    from tools.run_exit_gates import fail_direct_gate_run

    if __package__ is None:
        repo_root = Path(__file__).resolve().parents[3]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
    fail_direct_gate_run("gate_live_archive_sqlite")
