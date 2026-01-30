from __future__ import annotations

import re
from pathlib import Path
from typing import Tuple


def run() -> Tuple[bool, str]:
    root_dir = Path(__file__).resolve().parents[3]
    target = root_dir / "runtime" / "fxcm_forexconnect.py"
    if not target.exists():
        return False, f"gate_no_mutable_threading_event_default: file not found: {target}"
    text = target.read_text(encoding="utf-8")
    pattern = r"_stop_event\s*:\s*threading\.Event\s*=\s*threading\.Event\(\)"
    if re.search(pattern, text):
        return False, "FAIL: mutable default threading.Event() заборонений для _stop_event"
    return True, "OK: _stop_event не має mutable default"
