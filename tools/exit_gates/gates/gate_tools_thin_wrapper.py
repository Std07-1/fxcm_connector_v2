from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Tuple

from core.fixtures_path import repo_root

ALLOWED_TOOL_BASENAMES = {"run_exit_gates"}
ALLOWED_TOOL_DIRS = {"exit_gates"}
ALLOWED_DEFS = {"main", "parse_args"}


def _collect_pairs(root: Path) -> List[Tuple[Path, Path, str]]:
    runtime_dir = root / "runtime"
    tools_dir = root / "tools"
    pairs: List[Tuple[Path, Path, str]] = []
    for runtime_path in runtime_dir.glob("*.py"):
        if runtime_path.name == "__init__.py":
            continue
        name = runtime_path.stem
        tool_path = tools_dir / f"{name}.py"
        if not tool_path.exists():
            continue
        if name in ALLOWED_TOOL_BASENAMES:
            continue
        pairs.append((tool_path, runtime_path, name))
    return pairs


def _has_runtime_import(tree: ast.AST, name: str) -> bool:
    target = f"runtime.{name}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == target:
                    return True
        if isinstance(node, ast.ImportFrom):
            if node.module == target:
                return True
    return False


def _calls_runtime_main(tree: ast.AST, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr not in {"main", "run"}:
                continue
            value = node.func.value
            if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
                if value.value.id == "runtime" and value.attr == name:
                    return True
    return False


def _invalid_defs(tree: ast.AST) -> List[str]:
    invalid: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            invalid.append(f"class {node.name}")
        if isinstance(node, ast.FunctionDef) and node.name not in ALLOWED_DEFS:
            invalid.append(f"def {node.name}")
    return invalid


def check_tools_thin_wrapper(root: Path) -> Tuple[bool, str]:
    violations: List[str] = []
    for tool_path, _runtime_path, name in _collect_pairs(root):
        if any(part in ALLOWED_TOOL_DIRS for part in tool_path.parts):
            continue
        content = tool_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        if not _has_runtime_import(tree, name):
            violations.append(f"{tool_path}: немає імпорту runtime.{name}")
        if not _calls_runtime_main(tree, name):
            violations.append(f"{tool_path}: немає виклику runtime.{name}.main/run")
        invalid_defs = _invalid_defs(tree)
        if invalid_defs:
            violations.append(f"{tool_path}: заборонені визначення {', '.join(invalid_defs)}")
    if not violations:
        return True, "OK: R3 tools thin wrapper дотримано"
    message = "R3 порушено: tools дублюють runtime\n" + "\n".join(violations)
    return False, message


def run() -> Tuple[bool, str]:
    return check_tools_thin_wrapper(repo_root())
