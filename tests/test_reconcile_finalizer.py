from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional, Tuple

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.reconcile_finalizer import reconcile_final_tail
from runtime.status import StatusManager
from store.file_cache.history_cache import FileCache


class DummyHistoryProvider:
    def __init__(self, bars: List[dict]) -> None:
        self._bars = list(bars)

    def fetch_1m_final(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[dict]:
        rows = [b for b in self._bars if start_ms <= int(b["open_time_ms"]) <= end_ms]
        return rows[: int(limit)]

    def is_history_ready(self) -> Tuple[bool, str]:
        return True, ""

    def should_backoff(self, now_ms: int) -> bool:
        return False

    def note_not_ready(self, now_ms: int, reason: str) -> int:
        return int(now_ms)


class DummyPublisher:
    def __init__(self) -> None:
        self.final_1m: List[dict] = []
        self.final_htf: List[dict] = []

    def publish_ohlcv_final_1m(self, symbol: str, bars: list, validator: SchemaValidator) -> None:
        self.final_1m.extend(list(bars))

    def publish_ohlcv_final_htf(self, symbol: str, tf: str, bars: list, validator: SchemaValidator) -> None:
        self.final_htf.extend(list(bars))


class InMemoryPublisher:
    def __init__(self) -> None:
        self.last_snapshot: Optional[str] = None
        self.last_channel: Optional[str] = None

    def set_snapshot(self, key: str, json_str: str) -> None:
        self.last_snapshot = json_str

    def publish(self, channel: str, json_str: str) -> None:
        self.last_channel = channel


def _history_bar(open_ms: int) -> dict:
    close_ms = open_ms + 60_000 - 1
    return {
        "open_time_ms": int(open_ms),
        "close_time_ms": int(close_ms),
        "open": 1.0,
        "high": 1.2,
        "low": 0.8,
        "close": 1.1,
        "volume": 10.0,
    }


def test_reconcile_filters_already_finalized_1m_bars() -> None:
    config = Config(reconcile_enable=True)
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

    base_open = 1_700_000_000_000
    base_open -= base_open % 900_000
    bars = [_history_bar(base_open - 5 * 60_000 + i * 60_000) for i in range(20)]
    provider = DummyHistoryProvider(bars)

    with TemporaryDirectory() as tmp_dir:
        cache = FileCache(root=Path(tmp_dir), max_bars=200, warmup_bars=0, strict=True)
        cache.mark_published("XAUUSD", "1m", int(base_open + 9 * 60_000))
        publisher = DummyPublisher()
        reconcile_final_tail(
            config=config,
            file_cache=cache,
            provider=provider,
            publisher=publisher,
            validator=validator,
            status=status,
            metrics=None,
            symbol="XAUUSD",
            lookback_minutes=20,
            req_id="test",
            target_close_ms=int(base_open + 15 * 60_000 - 1),
        )

    assert len(publisher.final_1m) == 5


def test_reconcile_publishes_final_only_history_source() -> None:
    config = Config(reconcile_enable=True)
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

    base_open = 1_700_000_000_000
    base_open -= base_open % 900_000
    bars = [_history_bar(base_open + i * 60_000) for i in range(15)]
    provider = DummyHistoryProvider(bars)

    with TemporaryDirectory() as tmp_dir:
        cache = FileCache(root=Path(tmp_dir), max_bars=200, warmup_bars=0, strict=True)
        publisher = DummyPublisher()
        reconcile_final_tail(
            config=config,
            file_cache=cache,
            provider=provider,
            publisher=publisher,
            validator=validator,
            status=status,
            metrics=None,
            symbol="XAUUSD",
            lookback_minutes=20,
            req_id="test",
            target_close_ms=int(base_open + 15 * 60_000 - 1),
        )

    assert publisher.final_1m
    assert all(bar.get("source") == "history" for bar in publisher.final_1m)
    assert publisher.final_htf
    assert all(bar.get("source") == "history_agg" for bar in publisher.final_htf)


def test_reconcile_triggers_htf_rebuild_history_agg() -> None:
    config = Config(reconcile_enable=True)
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

    base_open = 1_700_000_000_000
    base_open -= base_open % 900_000
    bars = [_history_bar(base_open + i * 60_000) for i in range(15)]
    provider = DummyHistoryProvider(bars)

    with TemporaryDirectory() as tmp_dir:
        cache = FileCache(root=Path(tmp_dir), max_bars=200, warmup_bars=0, strict=True)
        publisher = DummyPublisher()
        reconcile_final_tail(
            config=config,
            file_cache=cache,
            provider=provider,
            publisher=publisher,
            validator=validator,
            status=status,
            metrics=None,
            symbol="XAUUSD",
            lookback_minutes=20,
            req_id="test",
            target_close_ms=int(base_open + 15 * 60_000 - 1),
        )
        rows, meta = cache.load("XAUUSD", "15m")

    assert publisher.final_htf
    assert len(rows) == 1
    assert meta.get("last_write_source") == "history_agg"
