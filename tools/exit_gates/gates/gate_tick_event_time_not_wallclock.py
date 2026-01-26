from __future__ import annotations

import re
from pathlib import Path
from typing import Tuple


def run() -> Tuple[bool, str]:
    root_dir = Path(__file__).resolve().parents[3]
    target = root_dir / "runtime" / "fxcm_forexconnect.py"
    if not target.exists():
        return False, f"gate_tick_event_time_not_wallclock: file not found: {target}"
    text = target.read_text(encoding="utf-8")
    patterns = [
        r"tick_ts_ms\s*=\s*now_ms",
        r"tick_ts_ms\s*=\s*int\(time\.time\(\)\s*\*\s*1000\)",
    ]
    for pattern in patterns:
        if re.search(pattern, text):
            return False, "tick_ts_ms не має братися з time.time(); очікується FXCM event time"
    return True, "OK: tick_ts_ms не з wall-clock"
