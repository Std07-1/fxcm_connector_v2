from __future__ import annotations

from pathlib import Path
from typing import Tuple


def _scan_file(path: Path) -> Tuple[bool, str]:
    text = path.read_text(encoding="utf-8")
    if "fetch_1m_final" not in text and "fetch_history" not in text:
        return True, ""
    if "guard_history_ready" in text:
        return True, ""
    return False, f"missing guard_history_ready in {path.as_posix()}"


def run() -> Tuple[bool, str]:
    root = Path(__file__).resolve().parents[3]
    files = [
        root / "runtime" / "warmup.py",
        root / "runtime" / "backfill.py",
        root / "runtime" / "repair.py",
        root / "runtime" / "tail_guard.py",
    ]
    for path in files:
        ok, msg = _scan_file(path)
        if not ok:
            return False, msg
    return True, "OK: guard_history_ready present at fetch callsites"
