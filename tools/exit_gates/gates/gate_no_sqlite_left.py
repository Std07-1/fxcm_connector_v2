from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

from tools.run_exit_gates import fail_direct_gate_run

MARKERS = [
    "sqlite3",
    "schema.sql",
    "sqlite_store",
    "upsert_1m_final",
    "rebuild_derived",
]

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    ".mypy_cache",
    "__pycache__",
    "reports",
    "Work",
    "data",
    "docs",
    "tools/audit",
    "docs/audit",
    "docs/audit_v2",
    "docs/audit_v3",
    "docs/audit_v6",
    "docs/audit_v7",
}

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".toml",
    ".ini",
    ".yml",
    ".yaml",
    ".ps1",
    ".sh",
}


def _is_excluded(path: Path) -> bool:
    parts = [p.replace("\\", "/") for p in path.parts]
    if not parts:
        return False
    for idx in range(len(parts)):
        chunk = "/".join(parts[idx:])
        if chunk in EXCLUDED_DIRS:
            return True
        if parts[idx] in EXCLUDED_DIRS:
            return True
    return False


def _scan_text(path: Path) -> List[str]:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
    hits = []
    lower = content.lower()
    for marker in MARKERS:
        if marker in lower:
            hits.append(marker)
    return hits


def _scan_paths(root: Path) -> List[Tuple[Path, str]]:
    findings: List[Tuple[Path, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        path = Path(dirpath)
        if _is_excluded(path):
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if not _is_excluded(path / d)]
        for name in filenames:
            file_path = path / name
            if _is_excluded(file_path):
                continue
            if file_path.name == "gate_no_sqlite_left.py":
                continue
            hits = _scan_text(file_path)
            for marker in hits:
                findings.append((file_path, marker))
    return findings


def run() -> Tuple[bool, str]:
    root = Path(__file__).resolve().parents[3]
    findings = _scan_paths(root)
    if findings:
        lines = [f"{p}: {marker}" for p, marker in findings]
        return False, "FAIL: sqlite маркери\n" + "\n".join(lines)
    return True, "OK: no sqlite markers"


if __name__ == "__main__":
    fail_direct_gate_run("gate_no_sqlite_left")
