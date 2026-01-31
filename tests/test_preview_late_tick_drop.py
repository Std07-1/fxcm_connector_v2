from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Dict, List, Optional

from config.config import Config
from core.fixtures_path import fixture_path
from core.time.buckets import TF_TO_MS
from runtime.preview_builder import OhlcvCache, PreviewBuilder


class _DummyStatus:
    def __init__(self) -> None:
        self.errors: List[Dict[str, Any]] = []
        self.degraded: List[str] = []
        self.preview_rail: Dict[str, Any] = {}

    def append_error(
        self,
        code: str,
        severity: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry: Dict[str, Any] = {"code": code, "severity": severity, "message": message}
        if context:
            entry["context"] = context
        self.errors.append(entry)

    def mark_degraded(self, code: str) -> None:
        if code not in self.degraded:
            self.degraded.append(code)

    def record_ohlcv_preview_rail(
        self,
        tf: str,
        last_tick_ts_ms: int,
        last_bucket_open_ms: int,
        late_ticks_dropped_total: int,
        misaligned_open_time_total: int,
        past_mutations_total: int,
        last_late_tick: Dict[str, int],
    ) -> None:
        self.preview_rail = {
            "tf": tf,
            "last_tick_ts_ms": last_tick_ts_ms,
            "last_bucket_open_ms": last_bucket_open_ms,
            "late_ticks_dropped_total": late_ticks_dropped_total,
            "misaligned_open_time_total": misaligned_open_time_total,
            "past_mutations_total": past_mutations_total,
            "last_late_tick": dict(last_late_tick),
        }


def test_preview_late_tick_drop_and_no_mutation() -> None:
    fixture = fixture_path("ticks_out_of_order_boundary.jsonl")
    lines = [line for line in fixture.read_text(encoding="utf-8").splitlines() if line.strip()]

    config = Config(ns="fxcm_local", commands_enabled=False)
    config = replace(config, ohlcv_preview_tfs=["1m"])
    cache = OhlcvCache()
    status = _DummyStatus()
    builder = PreviewBuilder(config=config, cache=cache, status=status)

    symbol = "XAUUSD"
    tf_ms = TF_TO_MS["1m"]
    current_bucket = None
    prev_bucket = None
    expected_close = None

    for line in lines:
        tick = json.loads(line)
        tick_ts_ms = int(tick.get("tick_ts_ms", 0))
        mid = float(tick.get("mid", 0.0))
        bucket_open = tick_ts_ms // tf_ms * tf_ms
        if current_bucket is None:
            current_bucket = bucket_open
        if bucket_open == current_bucket and prev_bucket is None:
            expected_close = mid
        elif bucket_open > current_bucket and prev_bucket is None:
            prev_bucket = current_bucket
            current_bucket = bucket_open
        builder.on_tick(symbol=symbol, mid=mid, tick_ts_ms=tick_ts_ms)

    state = builder.get_stream_state(symbol, "1m")
    assert state is not None
    assert state.late_ticks_dropped_total == 1
    assert state.past_mutations_total == 1
    assert status.preview_rail.get("late_ticks_dropped_total") == 1
    assert any(err.get("code") == "ohlcv_preview_late_tick_dropped" for err in status.errors)
    assert "ohlcv_preview_late_tick_dropped" in status.degraded

    bars = cache.get_tail(symbol, "1m", limit=10)
    assert prev_bucket is not None and expected_close is not None
    prev_bar = next(bar for bar in bars if int(bar["open_time"]) == int(prev_bucket))
    assert float(prev_bar["close"]) == float(expected_close)

    payloads = builder.build_payloads(symbol, limit=10)
    assert payloads
    payload_bars = payloads[0]["bars"]
    open_times = [int(bar["open_time"]) for bar in payload_bars]
    assert open_times == sorted(open_times)
