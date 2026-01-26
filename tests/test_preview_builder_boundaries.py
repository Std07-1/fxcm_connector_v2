from __future__ import annotations

from config.config import Config
from runtime.preview_builder import OhlcvCache, PreviewBuilder


def test_preview_builder_boundaries() -> None:
    config = Config(ohlcv_preview_tfs=["1m", "5m"], ohlcv_preview_enabled=True)
    cache = OhlcvCache()
    builder = PreviewBuilder(config=config, cache=cache)

    ts = 1_736_980_000_000
    builder.on_tick(symbol="XAUUSD", mid=2000.0, tick_ts_ms=ts)

    bars_1m = cache.get_tail("XAUUSD", "1m", 1)
    bars_5m = cache.get_tail("XAUUSD", "5m", 1)

    assert bars_1m[0]["close_time"] == bars_1m[0]["open_time"] + 60_000 - 1
    assert bars_5m[0]["close_time"] == bars_5m[0]["open_time"] + 300_000 - 1
