from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Tuple

FORBIDDEN_IMPORTS = [
    "runtime.tick_simulator",
    "runtime.ohlcv_preview_simulator",
    "runtime.history_sim_provider",
    "runtime.ohlcv_sim",
    "runtime.tick_sim",
]

ALLOWED_SIM_RUNTIME_PATTERNS = ("sim",)


def _iter_scan_roots(root: Path) -> Iterable[Path]:
    return [root / "app", root / "runtime"]


def _is_runtime_sim_stub(path: Path) -> bool:
    if "runtime" not in path.parts:
        return False
    return any(token in path.name for token in ALLOWED_SIM_RUNTIME_PATTERNS)


def run() -> Tuple[bool, str]:
    root = Path(__file__).resolve().parents[3]
    hits: List[str] = []
    for base in _iter_scan_roots(root):
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if _is_runtime_sim_stub(path):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in FORBIDDEN_IMPORTS:
                if pattern in text:
                    hits.append(str(path.relative_to(root)))
                    break
    if hits:
        sample = ", ".join(hits[:10])
        return False, f"FAIL: знайдено runtime sim імпорти: {sample}"
    return True, "OK: runtime/app не містять sim імпортів"
