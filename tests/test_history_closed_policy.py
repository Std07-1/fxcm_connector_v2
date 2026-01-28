from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import pytest

from config.config import Config
from core.time.calendar import Calendar
from core.time.timestamps import to_epoch_ms_utc
from core.validation.validator import SchemaValidator
from runtime.backfill import run_backfill
from runtime.history_provider import HistoryNotReadyError
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager
from store.sqlite_store import SQLiteStore


class DummyRedis:
    def publish(self, channel: str, value: str) -> None:
        return None

    def set(self, key: str, value: str) -> None:
        return None


class ReadyProbeProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.ready = True
        self.retry_after_ms = 0
        self.backoff_ms = 60_000
        self.backoff_max_ms = 5 * 60_000

    def fetch_1m_final(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[Dict[str, object]]:
        self.calls += 1
        bars: List[Dict[str, object]] = []
        t = start_ms - (start_ms % 60_000)
        while t <= end_ms and len(bars) < limit:
            bars.append(
                {
                    "symbol": symbol,
                    "open_time_ms": t,
                    "close_time_ms": t + 60_000 - 1,
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 1.0,
                    "complete": 1,
                    "synthetic": 0,
                    "source": "history",
                    "event_ts_ms": t + 60_000 - 1,
                }
            )
            t += 60_000
        return bars

    def is_history_ready(self):
        return bool(self.ready), "PriceHistoryCommunicator is not ready" if not self.ready else ""

    def should_backoff(self, now_ms: int) -> bool:
        return int(now_ms) < int(self.retry_after_ms)

    def note_not_ready(self, now_ms: int, reason: str) -> int:
        _ = reason
        if int(self.retry_after_ms) > int(now_ms):
            return int(self.retry_after_ms)
        if int(self.retry_after_ms) <= 0:
            backoff_ms = int(self.backoff_ms)
        else:
            backoff_ms = min(int(self.backoff_ms) * 2, int(self.backoff_max_ms))
        self.backoff_ms = int(backoff_ms)
        self.retry_after_ms = int(now_ms) + int(backoff_ms)
        return int(self.retry_after_ms)


def _ms(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return to_epoch_ms_utc(datetime(year, month, day, hour, minute, tzinfo=timezone.utc))


def test_closed_history_ready_allows_fetch(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.sqlite"
    store = SQLiteStore(db_path=db)
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store.init_schema(schema)

    config = Config(store_path=str(db))
    calendar = Calendar([], config.calendar_tag)
    status = StatusManager(
        config=config,
        validator=SchemaValidator(root_dir=Path(__file__).resolve().parents[1]),
        publisher=RedisPublisher(DummyRedis(), config),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    provider = ReadyProbeProvider()
    fixed_now_ms = _ms(2026, 1, 25, 20, 6)
    monkeypatch.setattr("runtime.backfill.time.time", lambda: fixed_now_ms / 1000)

    run_backfill(
        config=config,
        store=store,
        provider=provider,
        status=status,
        metrics=None,
        symbol="XAUUSD",
        start_ms=fixed_now_ms - 60 * 60_000,
        end_ms=fixed_now_ms - 1,
        publish_callback=None,
        rebuild_callback=None,
    )

    assert provider.calls > 0
    errors = status.snapshot().get("errors", [])
    assert not any(err.get("code") == "fxcm_history_not_ready" for err in errors)


def test_closed_history_not_ready_drops_and_sets_next_open_and_retry(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.sqlite"
    store = SQLiteStore(db_path=db)
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store.init_schema(schema)

    config = Config(store_path=str(db))
    calendar = Calendar([], config.calendar_tag)
    status = StatusManager(
        config=config,
        validator=SchemaValidator(root_dir=Path(__file__).resolve().parents[1]),
        publisher=RedisPublisher(DummyRedis(), config),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    provider = ReadyProbeProvider()
    provider.ready = False
    fixed_now_ms = _ms(2026, 1, 25, 20, 6)
    monkeypatch.setattr("runtime.backfill.time.time", lambda: fixed_now_ms / 1000)

    with pytest.raises(HistoryNotReadyError):
        run_backfill(
            config=config,
            store=store,
            provider=provider,
            status=status,
            metrics=None,
            symbol="XAUUSD",
            start_ms=fixed_now_ms - 60 * 60_000,
            end_ms=fixed_now_ms - 1,
            publish_callback=None,
            rebuild_callback=None,
        )

    assert provider.calls == 0
    history = status.snapshot().get("history", {})
    expected_open_ms = _ms(2026, 1, 25, 22, 0)
    assert int(history.get("next_trading_open_ms", 0)) == expected_open_ms
    assert int(history.get("history_retry_after_ms", 0)) > fixed_now_ms
    errors = status.snapshot().get("errors", [])
    assert any(err.get("code") == "fxcm_history_not_ready" for err in errors)


def test_backoff_prevents_spam(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.sqlite"
    store = SQLiteStore(db_path=db)
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store.init_schema(schema)

    config = Config(store_path=str(db))
    calendar = Calendar([], config.calendar_tag)
    status = StatusManager(
        config=config,
        validator=SchemaValidator(root_dir=Path(__file__).resolve().parents[1]),
        publisher=RedisPublisher(DummyRedis(), config),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    provider = ReadyProbeProvider()
    provider.ready = False
    fixed_now_ms = _ms(2026, 1, 25, 20, 6)
    monkeypatch.setattr("runtime.backfill.time.time", lambda: fixed_now_ms / 1000)

    with pytest.raises(HistoryNotReadyError):
        run_backfill(
            config=config,
            store=store,
            provider=provider,
            status=status,
            metrics=None,
            symbol="XAUUSD",
            start_ms=fixed_now_ms - 60 * 60_000,
            end_ms=fixed_now_ms - 1,
            publish_callback=None,
            rebuild_callback=None,
        )

    first_retry_after = int(status.snapshot().get("history", {}).get("history_retry_after_ms", 0))

    later_ms = fixed_now_ms + 10_000
    monkeypatch.setattr("runtime.backfill.time.time", lambda: later_ms / 1000)

    with pytest.raises(HistoryNotReadyError):
        run_backfill(
            config=config,
            store=store,
            provider=provider,
            status=status,
            metrics=None,
            symbol="XAUUSD",
            start_ms=later_ms - 60 * 60_000,
            end_ms=later_ms - 1,
            publish_callback=None,
            rebuild_callback=None,
        )

    second_retry_after = int(status.snapshot().get("history", {}).get("history_retry_after_ms", 0))
    assert provider.calls == 0
    assert second_retry_after >= first_retry_after
