from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from config.config import Config
from runtime.http_server import HttpServer
from runtime.preview_builder import OhlcvCache
from store.sqlite_store import SQLiteStore


class FakeRedis:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload)

    def get(self, key: str) -> str:
        return self._raw


def test_http_api_smoke(tmp_path: Path) -> None:
    status_payload = {"ok": True}
    cache = OhlcvCache()
    cache.update_bar(
        "XAUUSD",
        "1m",
        {
            "open_time": 1_736_980_000_000,
            "close_time": 1_736_980_000_000 + 60_000 - 1,
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.0,
            "volume": 1.0,
            "tick_count": 1,
            "complete": False,
            "synthetic": False,
            "source": "stream",
        },
    )
    db = tmp_path / "test.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)
    store.upsert_htf_final(
        "XAUUSD",
        "15m",
        [
            {
                "symbol": "XAUUSD",
                "open_time_ms": 1_736_980_000_000,
                "close_time_ms": 1_736_980_000_000 + 900_000 - 1,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "volume": 15.0,
                "complete": 1,
                "synthetic": 0,
                "source": "history_agg",
                "event_ts_ms": 1_736_980_000_000 + 900_000 - 1,
                "ingest_ts_ms": 1_736_980_100_000,
            }
        ],
    )
    server = HttpServer(
        config=Config(http_port=0),
        redis_client=FakeRedis(status_payload),
        cache=cache,
        store=store,
    )
    server.start()
    port = server.port()

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["ok"] is True

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ohlcv?symbol=XAUUSD&tf=1m&limit=10") as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["tf"] == "1m"
        assert len(data["bars"]) == 1

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ohlcv?symbol=XAUUSD&tf=15m&mode=final") as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["tf"] == "15m"
        assert len(data["bars"]) == 1

    server.stop()
