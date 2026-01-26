from __future__ import annotations

from pathlib import Path
from typing import List


def _read(rel_path: str) -> List[str]:
    root = Path(__file__).resolve().parents[1]
    return (root / rel_path).read_text(encoding="utf-8").splitlines()


def test_main_has_no_sim_imports() -> None:
    content = _read("app/main.py")
    forbidden = [
        "TickSimulator",
        "OhlcvPreviewSimulator",
        "OhlcvSimulator",
        "HistorySimProvider",
        "SimProvider",
        "Simulator",
    ]
    joined = "\n".join(content)
    assert not any(token in joined for token in forbidden)


def test_composition_sim_imports_only_in_sim_branch() -> None:
    content = _read("app/composition.py")
    forbidden = [
        "TickSimulator",
        "OhlcvPreviewSimulator",
        "HistorySimProvider",
        "SimProvider",
        "Simulator",
    ]
    joined = "\n".join(content)
    assert not any(token in joined for token in forbidden)
