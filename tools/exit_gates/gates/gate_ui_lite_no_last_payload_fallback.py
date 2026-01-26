from __future__ import annotations

from pathlib import Path
from typing import Tuple


def run() -> Tuple[bool, str]:
    root = Path(__file__).resolve().parents[3]
    path = root / "ui_lite" / "server.py"
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    end = None
    for idx, line in enumerate(lines):
        if line.startswith("async def _ws_handler"):
            start = idx
            continue
        if start is not None and line.startswith("def _start_redis_subscriber"):
            end = idx
            break
    if start is None or end is None:
        return False, "Не знайдено _ws_handler у ui_lite/server.py"
    segment = "\n".join(lines[start:end])
    if "last_payload_" in segment:
        return False, "Виявлено fallback на last_payload у _ws_handler"
    return True, "OK: ui_lite no last_payload fallback"
