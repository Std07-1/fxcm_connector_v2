from __future__ import annotations

from typing import Tuple

from config.config import Config


def run() -> Tuple[bool, str]:
    config = Config()
    if config.tick_mode == "fxcm" and config.fxcm_backend != "forexconnect":
        return False, "FAIL: tick_mode=fxcm потребує fxcm_backend=forexconnect"
    return True, "OK: tick_mode=fxcm узгоджено з fxcm_backend"
