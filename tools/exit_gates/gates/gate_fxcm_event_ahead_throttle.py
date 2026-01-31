from __future__ import annotations

import subprocess
import sys
from typing import Tuple


def run() -> Tuple[bool, str]:
    cmd = [sys.executable, "-m", "pytest", "-k", "event_ahead_throttle", "-q"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as exc:  # noqa: BLE001
        return False, f"FAIL: не вдалося запустити pytest: {exc}"
    if result.returncode != 0:
        output = (result.stdout or "") + (result.stderr or "")
        output = output.strip() or "(no output)"
        return False, "FAIL: pytest -k event_ahead_throttle" + "\n" + output
    return True, "OK: event_ahead_throttle"
