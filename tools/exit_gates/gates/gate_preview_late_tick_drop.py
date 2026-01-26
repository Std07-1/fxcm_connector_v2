from __future__ import annotations

import json
from dataclasses import replace
from typing import Tuple

from config.config import Config
from core.fixtures_path import fixture_path
from core.time.buckets import TF_TO_MS
from runtime.preview_builder import OhlcvCache, PreviewBuilder


def run() -> Tuple[bool, str]:
    fixture = fixture_path("ticks_out_of_order_boundary.jsonl")
    if not fixture.exists():
        return False, "FAIL: ticks_out_of_order_boundary.jsonl відсутній"

    lines = [line for line in fixture.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return False, "FAIL: ticks_out_of_order_boundary.jsonl порожній"

    config = Config(ns="fxcm_local", commands_enabled=False)
    config = replace(config, ohlcv_preview_tfs=["1m"])
    cache = OhlcvCache()
    builder = PreviewBuilder(config=config, cache=cache)

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
    if state is None:
        return False, "FAIL: state для 1m відсутній"
    if state.late_ticks_dropped_total != 1:
        return False, f"FAIL: late_ticks_dropped_total={state.late_ticks_dropped_total} (очікувалось 1)"

    bars = cache.get_tail(symbol, "1m", limit=10)
    if prev_bucket is None or expected_close is None:
        return False, "FAIL: некоректний сценарій rollover у fixture"
    try:
        prev_bar = next(bar for bar in bars if int(bar["open_time"]) == int(prev_bucket))
    except StopIteration:
        return False, "FAIL: попередній бар не знайдено у кеші"
    if float(prev_bar["close"]) != float(expected_close):
        return False, "FAIL: попередній бар мутував після rollover"

    payloads = builder.build_payloads(symbol, limit=10)
    if not payloads:
        return False, "FAIL: payloads порожній"
    payload_bars = payloads[0]["bars"]
    open_times = [int(bar["open_time"]) for bar in payload_bars]
    if open_times != sorted(open_times):
        return False, "FAIL: bars не відсортовані за open_time"

    return True, "OK: late-tick drop rail та sorted publish працюють"
