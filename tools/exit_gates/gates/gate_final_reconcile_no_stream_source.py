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
from tools.run_exit_gates import fail_direct_gate_run


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


def run() -> Tuple[bool, str]:
    config = Config(reconcile_enable=True)
    root_dir = Path(__file__).resolve().parents[2]
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
            req_id="gate",
            target_close_ms=int(base_open + 15 * 60_000 - 1),
        )

    all_bars = list(publisher.final_1m) + list(publisher.final_htf)
    if not all_bars:
        return False, "FAIL: reconcile не опублікував final бари"
    for bar in all_bars:
        if bar.get("source") in {"stream", "stream_close"}:
            return False, "FAIL: reconcile має source=history/history_agg"
    return True, "OK: reconcile final без stream/stream_close"


if __name__ == "__main__":
    fail_direct_gate_run("gate_final_reconcile_no_stream_source")
