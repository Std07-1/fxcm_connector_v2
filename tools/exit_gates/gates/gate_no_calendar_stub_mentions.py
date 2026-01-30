from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple


def _iter_files(root: Path, exts: Iterable[str]) -> Iterable[Path]:
    ignore_dirs = {"__pycache__", ".mypy_cache", ".venv", "data", "Work", "reports", "docs"}
    for path in root.rglob("*"):
        if path.is_dir():
            if path.name in ignore_dirs:
                continue
            continue
        if path.suffix.lower() not in exts:
            continue
        if any(part in ignore_dirs for part in path.parts):
            continue
        yield path


def run() -> Tuple[bool, str]:
    repo_root = Path(__file__).resolve().parents[3]
    allowlist = {
        (repo_root / "tests" / "test_manifest_includes_calendar_gates.py").resolve(),
    }
    scan_roots = [
        repo_root / "app",
        repo_root / "core",
        repo_root / "runtime",
        repo_root / "ui_lite",
        repo_root / "tests",
        repo_root / "tools",
    ]
    exts = {".py"}
    hits = []
    self_path = Path(__file__).resolve()
    for root in scan_roots:
        if not root.exists():
            continue
        for file_path in _iter_files(root, exts):
            resolved = file_path.resolve()
            if resolved == self_path or resolved in allowlist:
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "calendar_stub" in text:
                rel = file_path.relative_to(repo_root)
                hits.append(str(rel))
    if hits:
        return False, "FAIL: знайдено calendar_stub у файлах: " + ", ".join(sorted(hits))
    return True, "OK: calendar_stub не згадується у runtime/test/tools коді"
