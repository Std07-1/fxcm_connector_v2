from __future__ import annotations

from store.derived_builder import build_htf_final


def test_build_htf_final_15m() -> None:
    base = 1_736_980_000_000
    bucket_start = base - (base % 900_000)
    bars_1m = []
    for i in range(15):
        open_time = bucket_start + i * 60_000
        bars_1m.append(
            {
                "open_time_ms": open_time,
                "close_time_ms": open_time + 60_000 - 1,
                "open": 1.0 + i,
                "high": 1.5 + i,
                "low": 0.5 + i,
                "close": 1.1 + i,
                "volume": 1.0,
            }
        )

    bars, skipped = build_htf_final(symbol="XAUUSD", tf="15m", bars_1m=bars_1m)
    assert skipped == 0
    assert len(bars) == 1
    bar = bars[0]
    assert bar["open_time_ms"] == bucket_start
    assert bar["close_time_ms"] == bucket_start + 900_000 - 1
    assert bar["open"] == 1.0
    assert bar["close"] == 1.1 + 14
    assert bar["high"] == 1.5 + 14
    assert bar["low"] == 0.5
    assert bar["volume"] == 15.0
    assert bar["source"] == "history_agg"
    assert bar["event_ts_ms"] == bar["close_time_ms"]
