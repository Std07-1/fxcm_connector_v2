from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Tuple

from core.fixtures_path import repo_root

FORBIDDEN_ASSIGNMENTS = {"open", "high", "low", "close", "open_time", "close_time"}


def _has_required_import(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "core.market.preview_1m_builder" in node.module:
                return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "core.market.preview_1m_builder" in alias.name:
                    return True
    return False


def _find_violations(tree: ast.AST) -> List[str]:
    violations: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            if "Preview" in node.name or "Builder" in node.name:
                violations.append(f"заборонений def/class: {node.name}")
        if isinstance(node, ast.FunctionDef):
            for inner in ast.walk(node):
                if isinstance(inner, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = []
                    if isinstance(inner, ast.Assign):
                        targets = inner.targets
                    else:
                        targets = [inner.target]
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id in FORBIDDEN_ASSIGNMENTS:
                            violations.append(f"заборонене присвоєння: {target.id}")
    return violations


def check_preview_builder_file(path: Path) -> Tuple[bool, str]:
    content = path.read_text(encoding="utf-8")
    tree = ast.parse(content)
    if not _has_required_import(tree):
        return False, "R2 порушено: немає імпорту core.market.preview_1m_builder"
    violations = _find_violations(tree)
    if violations:
        details = "; ".join(violations)
        return False, f"R2 порушено: preview SSOT дублюється в runtime ({details})"
    return True, "OK: R2 preview SSOT у core"


def run() -> Tuple[bool, str]:
    path = repo_root() / "runtime" / "preview_builder.py"
    if not path.exists():
        return False, "FAIL: runtime/preview_builder.py не знайдено"
    return check_preview_builder_file(path)
