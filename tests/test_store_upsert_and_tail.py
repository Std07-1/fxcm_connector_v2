from __future__ import annotations

import tempfile
from pathlib import Path

from store.bars_store import BarsStoreSQLite


def test_store_upsert_and_tail() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "bars.sqlite"
        store = BarsStoreSQLite(db_path=db_path, schema_path=root_dir / "store" / "schema.sql")
        store.migrate()
        store.upsert_bar(
            symbol="XAUUSD",
            tf="1m",
            open_time_ms=1_736_980_000_000,
            close_time_ms=1_736_980_059_999,
            open_p=1.0,
            high=1.2,
            low=0.9,
            close_p=1.1,
            volume=1.0,
            complete=True,
            synthetic=False,
            source="history",
        )
        store.upsert_bar(
            symbol="XAUUSD",
            tf="1m",
            open_time_ms=1_736_980_060_000,
            close_time_ms=1_736_980_119_999,
            open_p=1.1,
            high=1.3,
            low=1.0,
            close_p=1.2,
            volume=1.0,
            complete=True,
            synthetic=False,
            source="history",
        )
        tail = store.get_tail(symbol="XAUUSD", tf="1m", window_hours=1)
        assert len(tail) == 2
        assert tail[0]["open_time_ms"] < tail[1]["open_time_ms"]
