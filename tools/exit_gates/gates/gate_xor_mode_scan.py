from __future__ import annotations

from pathlib import Path
from typing import List, Tuple


def _read(rel_path: str) -> List[str]:
    root = Path(__file__).resolve().parents[3]
    return (root / rel_path).read_text(encoding="utf-8").splitlines()


def _scan_main() -> Tuple[bool, str]:
    content = _read("app/main.py")
    forbidden = [
        "TickSimulator",
        "OhlcvPreviewSimulator",
        "OhlcvSimulator",
        "HistorySimProvider",
        "SimProvider",
        "Simulator",
    ]
    if any(any(token in line for token in forbidden) for line in content):
        return False, "FAIL: app/main.py містить імпорти симуляторів"
    return True, "OK: main без симуляторів"


def _scan_composition() -> Tuple[bool, str]:
    content = _read("app/composition.py")
    forbidden = [
        "TickSimulator",
        "OhlcvPreviewSimulator",
        "HistorySimProvider",
        "SimProvider",
        "Simulator",
    ]
    joined = "\n".join(content)
    if any(token in joined for token in forbidden):
        return False, "FAIL: composition містить sim-імпорти"
    return True, "OK: composition без sim-імпортів"


def run() -> Tuple[bool, str]:
    ok_main, msg_main = _scan_main()
    ok_comp, msg_comp = _scan_composition()
    if ok_main and ok_comp:
        return True, f"{msg_main}; {msg_comp}"
    return False, f"{msg_main}; {msg_comp}"
