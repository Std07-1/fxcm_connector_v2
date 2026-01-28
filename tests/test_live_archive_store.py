from __future__ import annotations

from pathlib import Path

from store.live_archive_store import SqliteLiveArchiveStore


def test_live_archive_insert_and_duplicate(tmp_path: Path) -> None:
    db_path = tmp_path / "live_archive.sqlite"
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
    assert result.status == "INSERTED"
    dup = store.insert_bar(
        symbol="XAUUSD",
        tf="1m",
        open_time_ms=int(payload["open_time"]),
        close_time_ms=int(payload["close_time"]),
        payload=payload,
    )
    assert dup.status == "DUPLICATE"


def test_live_archive_geom_rail_rejects_invalid_close(tmp_path: Path) -> None:
    db_path = tmp_path / "live_archive.sqlite"
    store = SqliteLiveArchiveStore(db_path=db_path)
    store.init_schema()
    payload = {"open_time": 1_700_000_000_000, "close_time": 1_700_000_000_000}
    result = store.insert_bar(
        symbol="XAUUSD",
        tf="1m",
        open_time_ms=int(payload["open_time"]),
        close_time_ms=int(payload["close_time"]),
        payload=payload,
    )
    assert result.status == "FAILED"
