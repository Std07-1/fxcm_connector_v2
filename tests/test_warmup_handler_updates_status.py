from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.handlers_p3 import handle_warmup_command
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager
from store.sqlite_store import SQLiteStore
from tests.fixtures.sim.history_sim_provider import HistorySimProvider


class _DummyRedis:
    def publish(self, channel: str, payload: str) -> None:
        return None

    def set(self, key: str, value: str) -> None:
        return None


def test_warmup_handler_updates_status() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    config = Config(warmup_lookback_days=0)
    calendar = Calendar(
        closed_intervals_utc=config.closed_intervals_utc,
        calendar_tag=config.calendar_tag,
    )
    validator = SchemaValidator(root_dir=root_dir)
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=RedisPublisher(_DummyRedis(), config),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "bars.sqlite"
        store = SQLiteStore(db_path=db_path)
        store.init_schema(root_dir / "store" / "schema.sql")
        provider = HistorySimProvider(calendar=calendar)

        now_ms = int(time.time() * 1000)
        open_time_ms = now_ms - (now_ms % 60_000) - 60_000
        store.upsert_1m_final(
            "XAUUSD",
            [
                {
                    "symbol": "XAUUSD",
                    "open_time_ms": open_time_ms,
                    "close_time_ms": open_time_ms + 60_000 - 1,
                    "open": 2000.0,
                    "high": 2000.1,
                    "low": 1999.9,
                    "close": 2000.05,
                    "volume": 1.0,
                    "complete": 1,
                    "synthetic": 0,
                    "source": "history",
                    "event_ts_ms": open_time_ms + 60_000 - 1,
                    "ingest_ts_ms": now_ms,
                }
            ],
        )

        payload = {
            "cmd": "fxcm_warmup",
            "req_id": "test-warmup-0001",
            "ts": 1_736_980_000_000,
            "args": {"symbols": ["XAUUSD"], "lookback_days": 0, "publish": False, "window_hours": 1},
        }
        handle_warmup_command(
            payload=payload,
            config=config,
            store=store,
            provider=provider,
            status=status,
            metrics=None,
            publish_tail=lambda _symbol, _hours: None,
        )

    snapshot = status.snapshot()
    final_1m = snapshot.get("ohlcv_final_1m", {})
    assert int(final_1m.get("last_complete_bar_ms", 0)) > 0


def test_warmup_handler_empty_history_reports_error() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    config = Config(warmup_lookback_days=0)
    calendar = Calendar(
        closed_intervals_utc=config.closed_intervals_utc,
        calendar_tag=config.calendar_tag,
    )
    validator = SchemaValidator(root_dir=root_dir)
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=RedisPublisher(_DummyRedis(), config),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    class _EmptyProvider(HistorySimProvider):
        def fetch_1m_final(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, Any]]:
            _ = symbol
            _ = start_ms
            _ = end_ms
            _ = limit
            return []

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "bars.sqlite"
        store = SQLiteStore(db_path=db_path)
        store.init_schema(root_dir / "store" / "schema.sql")
        provider = _EmptyProvider(calendar=calendar)

        payload = {
            "cmd": "fxcm_warmup",
            "req_id": "test-warmup-0002",
            "ts": 1_736_980_000_000,
            "args": {"symbols": ["XAUUSD"], "lookback_days": 0, "publish": False, "window_hours": 1},
        }
        with pytest.raises(ValueError, match="SSOT 1m final порожній"):
            handle_warmup_command(
                payload=payload,
                config=config,
                store=store,
                provider=provider,
                status=status,
                metrics=None,
                publish_tail=lambda _symbol, _hours: None,
            )

    snapshot = status.snapshot()
    errors = snapshot.get("errors", [])
    assert any(err.get("code") == "warmup_empty_history" for err in errors)
