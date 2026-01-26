from __future__ import annotations

from pathlib import Path
from typing import Tuple

FILES = [
    "runtime/warmup.py",
    "runtime/backfill.py",
    "runtime/repair.py",
]


def _check_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "TokenBucket" in text:
        raise ValueError(f"TokenBucket заборонено у {path.as_posix()}")
    if path.name in {"warmup.py", "backfill.py"} and "min_sleep_ms" in text:
        raise ValueError(f"min_sleep_ms заборонено у {path.as_posix()}")


def run() -> Tuple[bool, str]:
    try:
        root = Path(__file__).resolve().parents[3]
        for rel in FILES:
            _check_file(root / rel)
    except Exception as exc:  # noqa: BLE001
        return False, f"FAIL: {exc}"
    return True, "OK: локальні TokenBucket/min_sleep у history відсутні"
