from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.backfill import run_backfill
from runtime.history_provider import HistoryNotReadyError
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager
from runtime.warmup import run_warmup
from store.sqlite_store import SQLiteStore


class _DummyRedis:
    def publish(self, channel: str, payload: str) -> None:
        return None

    def set(self, key: str, value: str) -> None:
        return None


class _NotReadyProvider:
    def __init__(self) -> None:
        self.fetch_calls: int = 0

    def fetch_1m_final(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, Any]]:
        self.fetch_calls += 1
        return []

    def is_history_ready(self) -> Tuple[bool, str]:
        return False, "not_ready"

    def should_backoff(self, now_ms: int) -> bool:
        return False

    def note_not_ready(self, now_ms: int, reason: str) -> int:
        _ = reason
        return int(now_ms) + 60_000


def _build_status(config: Config) -> StatusManager:
    root_dir = Path(__file__).resolve().parents[1]
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
    return status


def test_warmup_blocked_when_not_ready() -> None:
    config = Config(warmup_default_lookback_days=1)
    status = _build_status(config)
    provider = _NotReadyProvider()

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "bars.sqlite"
        store = SQLiteStore(db_path=db_path)
        store.init_schema(Path(__file__).resolve().parents[1] / "store" / "schema.sql")
        with pytest.raises(HistoryNotReadyError):
            run_warmup(
                config=config,
                store=store,
                provider=provider,
                status=status,
                metrics=None,
                symbols=["XAUUSD"],
                lookback_days=1,
                publish_callback=None,
            )
    assert provider.fetch_calls == 0
    errors = status.snapshot().get("errors", [])
    assert any(err.get("code") == "fxcm_history_not_ready" for err in errors)


def test_backfill_blocked_when_not_ready() -> None:
    config = Config()
    status = _build_status(config)
    provider = _NotReadyProvider()
    now_ms = int(time.time() * 1000)

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "bars.sqlite"
        store = SQLiteStore(db_path=db_path)
        store.init_schema(Path(__file__).resolve().parents[1] / "store" / "schema.sql")
        with pytest.raises(HistoryNotReadyError):
            run_backfill(
                config=config,
                store=store,
                provider=provider,
                status=status,
                metrics=None,
                symbol="XAUUSD",
                start_ms=now_ms - 2 * 60_000,
                end_ms=now_ms - 1,
                publish_callback=None,
            )
    assert provider.fetch_calls == 0
    errors = status.snapshot().get("errors", [])
    assert any(err.get("code") == "fxcm_history_not_ready" for err in errors)
