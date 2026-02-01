from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Optional, cast

import pytest

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import ContractError, SchemaValidator
from runtime.republish import republish_tail
from runtime.status import StatusManager
from store.file_cache.history_cache import FileCache


class DummyRedis:
    def __init__(self) -> None:
        self._store = {}

    def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    def setex(self, key: str, ttl_s: int, value: str) -> None:
        self._store[key] = value


class DummyPublisher:
    def __init__(self) -> None:
        self.published = []

    def publish_ohlcv_final_1m(self, symbol: str, bars: list, validator: SchemaValidator) -> None:
        self.published.append((symbol, "1m", bars))

    def publish_ohlcv_final_htf(self, symbol: str, tf: str, bars: list, validator: SchemaValidator) -> None:
        self.published.append((symbol, tf, bars))


class InMemoryPublisher:
    def __init__(self) -> None:
        self.last_snapshot: Optional[str] = None
        self.last_channel: Optional[str] = None

    def set_snapshot(self, key: str, json_str: str) -> None:
        self.last_snapshot = json_str

    def publish(self, channel: str, json_str: str) -> None:
        self.last_channel = channel


def _build_bar(open_ms: int) -> dict:
    close_ms = open_ms + 60_000 - 1
    return {
        "open_time": open_ms,
        "close_time": close_ms,
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": 1.05,
        "volume": 10.0,
        "tick_count": 5,
        "complete": True,
    }


def test_republish_rejects_stream_source_complete_true() -> None:
    config = Config()
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=InMemoryPublisher(),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    with TemporaryDirectory() as tmp_dir:
        cache = FileCache(root=Path(tmp_dir), max_bars=10, warmup_bars=0, strict=True)
        base = 1_700_000_000_000
        base -= base % 60_000
        cache.append_complete_bars(
            symbol="XAUUSD",
            tf="1m",
            bars=[_build_bar(base)],
            source="stream_close",
        )
        publisher = DummyPublisher()
        redis_client = DummyRedis()
        with pytest.raises(ContractError):
            republish_tail(
                config=config,
                file_cache=cache,
                redis_client=redis_client,
                publisher=cast(Any, publisher),
                validator=validator,
                status=status,
                metrics=None,
                symbol="XAUUSD",
                timeframes=["1m"],
                window_hours=1,
                force=True,
                req_id="test",
            )

    snapshot = status.snapshot()
    assert any(err.get("code") == "republish_source_invalid" for err in snapshot.get("errors", []))
