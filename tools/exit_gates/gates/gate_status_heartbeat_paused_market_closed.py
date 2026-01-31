from __future__ import annotations

import subprocess
import sys
from typing import Tuple


def run() -> Tuple[bool, str]:
    cmd = [sys.executable, "-m", "pytest", "-k", "status_heartbeat_paused_market_closed", "-q"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as exc:  # noqa: BLE001
        return False, f"FAIL: не вдалося запустити pytest: {exc}"
    if result.returncode != 0:
        output = (result.stdout or "") + (result.stderr or "")
        output = output.strip() or "(no output)"
        return False, "FAIL: pytest -k status_heartbeat_paused_market_closed" + "\n" + output
    return True, "OK: status_heartbeat_paused_market_closed"
