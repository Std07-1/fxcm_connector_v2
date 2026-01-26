from __future__ import annotations

import pytest

from app.composition import _ensure_no_sim
from config.config import Config


def test_fxcm_preview_conflict_with_sim_modes() -> None:
    config = Config(tick_mode="sim", preview_mode="off", ohlcv_sim_enabled=False)
    with pytest.raises(SystemExit):
        _ensure_no_sim(config)


def test_fxcm_preview_no_conflict_when_sims_off() -> None:
    config = Config(tick_mode="off", preview_mode="off", ohlcv_sim_enabled=False)
    _ensure_no_sim(config)
