from __future__ import annotations

from tools import soak_monitor


def test_soak_monitor_report_schema() -> None:
    summary = {
        "channel": "fxcm_local:ohlcv",
        "duration_s": 120,
        "bars_total": 10,
        "gaps_total": 0,
        "gap_events": 0,
        "largest_gap": 0,
        "duplicates": 0,
        "out_of_order": 0,
        "invalid_bars": 0,
        "max_gap_bars": 0,
        "last_open_time_ms": 1234567890,
        "events": [],
    }
    payload = soak_monitor.build_report_payload(
        summary=summary,
        ns="fxcm_local",
        symbol="XAUUSD",
        tf="1m",
        mode="preview",
    )
    for key in [
        "bars_total",
        "gaps_total",
        "max_gap_bars",
        "last_open_time_ms",
        "ns",
        "symbol",
        "tf",
        "mode",
    ]:
        assert key in payload
