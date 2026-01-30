from __future__ import annotations

from config.config import Config
from core.time.calendar import Calendar
from runtime.ohlcv_preview import PreviewCandleBuilder
from runtime.preview_builder import OhlcvCache


def test_preview_from_ticks_produces_bar_time_gt_zero() -> None:
    config = Config(ohlcv_preview_enabled=True)
    cache = OhlcvCache()
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    builder = PreviewCandleBuilder(config=config, cache=cache, calendar=calendar)

    builder.on_tick(symbol="XAUUSD", mid=2000.0, tick_ts_ms=1_700_000_000_000)
    payloads = builder.build_payloads(symbol="XAUUSD", limit=10)

    assert payloads
    bars = payloads[0]["bars"]
    assert bars
    bar = bars[0]
    assert int(bar["open_time"]) > 0
    assert int(bar["close_time"]) > int(bar["open_time"])
