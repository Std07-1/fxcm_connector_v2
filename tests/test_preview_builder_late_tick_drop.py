from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from config.config import Config
from core.fixtures_path import fixture_path
from core.time.buckets import TF_TO_MS
from runtime.preview_builder import OhlcvCache, PreviewBuilder


def _load_ticks() -> list[dict[str, Any]]:
    path = fixture_path("ticks_out_of_order_boundary.jsonl")
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_preview_builder_late_tick_drop() -> None:
    config = Config(ns="fxcm_local", commands_enabled=False)
    config = replace(config, ohlcv_preview_tfs=["1m"])
    cache = OhlcvCache()
    builder = PreviewBuilder(config=config, cache=cache)

    ticks = _load_ticks()
    symbol = "XAUUSD"
    tf_ms = TF_TO_MS["1m"]
    current_bucket: int | None = None
    prev_bucket: int | None = None
    expected_close: float | None = None

    for tick in ticks:
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

    bars = cache.get_tail(symbol, "1m", limit=10)
    assert prev_bucket is not None
    assert expected_close is not None
    prev_bar = next(bar for bar in bars if int(bar["open_time"]) == int(prev_bucket))
    assert float(prev_bar["close"]) == expected_close

    payloads = builder.build_payloads(symbol, limit=10)
    assert payloads
    payload_bars = payloads[0]["bars"]
    open_times = [int(bar["open_time"]) for bar in payload_bars]
    assert open_times == sorted(open_times)
