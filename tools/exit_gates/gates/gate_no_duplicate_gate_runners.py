from __future__ import annotations

from pathlib import Path
from typing import List, Tuple


def _find_alternative_runners(root: Path) -> List[Path]:
    patterns = [
        "tools/run_exit_gates_*.py",
        "tools/*exit*gates*.py",
        "tools/exit_gates/*runner*.py",
    ]
    matches: List[Path] = []
    for pattern in patterns:
        for path in root.rglob(pattern):
            if path.name == "run_exit_gates.py":
                continue
            matches.append(path)
    return matches


def _find_duplicate_gate_dirs(root: Path) -> List[Path]:
    duplicates: List[Path] = []
    for path in root.rglob("exit_gates"):
        if not path.is_dir():
            continue
        rel = path.relative_to(root)
        if ".mypy_cache" in rel.parts:
            continue
        if rel.parts[:2] == ("reports", "exit_gates"):
            continue
        if rel.parts[:2] == ("tools", "exit_gates"):
            continue
        duplicates.append(path)
    for path in root.rglob("gates"):
        if not path.is_dir():
            continue
        rel = path.relative_to(root)
        if ".mypy_cache" in rel.parts:
            continue
        if rel.parts[:3] == ("reports", "exit_gates", "gates"):
            continue
        if rel.parts[:3] == ("tools", "exit_gates", "gates"):
            continue
        if rel.parts[:1] == (".venv",):
            continue
        duplicates.append(path)
    return duplicates


def _find_gate_scripts_outside(root: Path) -> List[Path]:
    allowed_root = root / "tools" / "exit_gates" / "gates"
    legacy_wrappers = {
        root / "tools" / "exit_gates" / "gate_calendar_gaps.py",
        root / "tools" / "exit_gates" / "gate_final_wire.py",
        root / "tools" / "exit_gates" / "gate_no_mix.py",
        root / "tools" / "exit_gates" / "gate_republish_watermark.py",
    }
    matches: List[Path] = []
    for path in root.rglob("gate_*.py"):
        if allowed_root in path.parents:
            continue
        if path in legacy_wrappers:
            continue
        if path.name == "__init__.py":
            continue
        if ".venv" in path.parts:
            continue
        matches.append(path)
    return matches


def run() -> Tuple[bool, str]:
    root = Path(__file__).resolve().parents[3]
    runners = _find_alternative_runners(root)
    dup_dirs = _find_duplicate_gate_dirs(root)
    stray_gates = _find_gate_scripts_outside(root)

    issues = []
    if runners:
        issues.append("альтернативні runner-и: " + ", ".join(str(p) for p in runners))
    if dup_dirs:
        issues.append("дублікати gate директорій: " + ", ".join(str(p) for p in dup_dirs))
    if stray_gates:
        issues.append("gate-скрипти поза tools/exit_gates/gates: " + ", ".join(str(p) for p in stray_gates))

    if issues:
        return False, "FAIL: " + " | ".join(issues)
    return True, "OK: один runner, один набір gates"
