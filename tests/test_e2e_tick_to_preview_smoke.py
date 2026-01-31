from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import List

from config.config import Config
from core.market.tick import normalize_tick
from core.validation.validator import SchemaValidator
from observability.metrics import create_metrics
from runtime.preview_builder import OhlcvCache, PreviewBuilder
from runtime.status import StatusManager


class _FakePublisher:
    def __init__(self) -> None:
        self.snapshots: List[str] = []
        self.published: List[str] = []

    def set_snapshot(self, key: str, json_str: str) -> None:
        self.snapshots.append(json_str)

    def publish(self, channel: str, json_str: str) -> None:
        self.published.append(json_str)


def _build_status(config: Config) -> StatusManager:
    validator = SchemaValidator(root_dir=Path(__file__).resolve().parents[1])
    metrics = create_metrics()
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=_FakePublisher(),
        calendar=validator._calendar(),
        metrics=metrics,
    )
    status.build_initial_snapshot()
    return status


def _validate_tick_payload(validator: SchemaValidator, symbol: str, bid: float, ask: float, tick_ts_ms: int) -> None:
    payload = {
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2.0,
        "tick_ts": tick_ts_ms,
        "snap_ts": tick_ts_ms,
    }
    validator.validate_tick_v1(payload)


def test_e2e_tick_to_preview_smoke() -> None:
    config = replace(Config(), ohlcv_preview_tfs=["1m"], commands_enabled=False)
    status = _build_status(config)
    validator = SchemaValidator(root_dir=Path(__file__).resolve().parents[1])
    cache = OhlcvCache()
    builder = PreviewBuilder(config=config, cache=cache, status=status)

    symbol = "XAUUSD"
    now_ms = int(time.time() * 1000)
    bucket_open_ms = (now_ms // 60_000) * 60_000

    tick_a_ms = bucket_open_ms + 1_000
    tick_b_ms = bucket_open_ms + 20_000
    tick_c_ms = bucket_open_ms - 1_000

    for tick_ms, bid, ask in [
        (tick_a_ms, 2000.0, 2000.2),
        (tick_b_ms, 2000.1, 2000.4),
        (tick_c_ms, 1999.9, 2000.1),
    ]:
        _validate_tick_payload(validator, symbol, bid, ask, tick_ms)
        tick = normalize_tick(symbol=symbol, bid=bid, ask=ask, tick_ts_ms=tick_ms, snap_ts_ms=tick_ms)
        status.record_tick(tick_ts_ms=tick.tick_ts_ms, snap_ts_ms=tick.snap_ts_ms, now_ms=tick.snap_ts_ms)
        builder.on_tick(symbol=symbol, mid=tick.mid, tick_ts_ms=tick.tick_ts_ms)

    bars = cache.get_tail(symbol, "1m", limit=10)
    assert len(bars) == 1

    state = builder.get_stream_state(symbol, "1m")
    assert state is not None
    assert state.late_ticks_dropped_total == 1
    assert state.past_mutations_total == 1

    snapshot = status.snapshot()
    preview = snapshot.get("ohlcv_preview", {})
    assert int(preview.get("late_ticks_dropped_total", 0)) == 1
