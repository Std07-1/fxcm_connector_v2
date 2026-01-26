from __future__ import annotations

import sys
from typing import Tuple


def run() -> Tuple[bool, str]:
    current = f"{sys.version_info.major}.{sys.version_info.minor}"
    if sys.version_info[:2] == (3, 7):
        return True, f"OK: python_version={current}"
    return False, f"FAIL: python_version={current} (очікується 3.7; запускати через .venv)"
