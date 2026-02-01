from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, Optional, Tuple, cast

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import ContractError, SchemaValidator
from runtime.republish import republish_tail
from runtime.status import StatusManager
from store.file_cache.history_cache import FileCache
from tools.run_exit_gates import fail_direct_gate_run


class DummyRedis:
    def __init__(self) -> None:
        self._store: Dict[str, str] = {}

    def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    def setex(self, key: str, ttl_s: int, value: str) -> None:
        self._store[key] = value


class DummyPublisher:
    def publish_ohlcv_final_1m(self, symbol: str, bars: list, validator: SchemaValidator) -> None:
        return

    def publish_ohlcv_final_htf(self, symbol: str, tf: str, bars: list, validator: SchemaValidator) -> None:
        return


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


def run() -> Tuple[bool, str]:
    config = Config()
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
        try:
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
                req_id="gate",
            )
        except ContractError:
            if any(err.get("code") == "republish_source_invalid" for err in status.snapshot().get("errors", [])):
                return True, "OK: republish відхилено для stream/stream_close"
            return False, "FAIL: немає republish_source_invalid у status"
        return False, "FAIL: republish не відхилив stream/stream_close"


if __name__ == "__main__":
    fail_direct_gate_run("gate_final_republish_source_allowlist")
