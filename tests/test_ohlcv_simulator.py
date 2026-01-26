from __future__ import annotations

from config.config import Config
from tests.fixtures.sim.ohlcv_sim import OhlcvSimulator


def test_ohlcv_simulator_disabled() -> None:
    sim = OhlcvSimulator(config=Config(ohlcv_sim_enabled=False))
    assert sim.maybe_tick(now_ms=1_736_980_000_000) is None


def test_ohlcv_simulator_emits() -> None:
    sim = OhlcvSimulator(config=Config(ohlcv_sim_enabled=True, tick_sim_interval_ms=0))
    price = sim.maybe_tick(now_ms=1_736_980_000_000)
    assert price is not None
