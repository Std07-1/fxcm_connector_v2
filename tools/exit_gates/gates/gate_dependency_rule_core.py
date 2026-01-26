from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Sequence, Tuple

from core.fixtures_path import repo_root

BANNED_PREFIXES = ("runtime", "store", "ui_lite", "tools", "app", "observability")


def _module_path_for_file(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = rel.parts
    return ".".join(parts)


def _resolve_import(current_module: str, module: str, level: int) -> str:
    if level == 0:
        return module
    parts = current_module.split(".")
    package_parts = parts[:-1]
    up = max(0, level - 1)
    base = package_parts[: len(package_parts) - up]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


def scan_core_imports(root: Path) -> List[Tuple[str, int, str]]:
    violations: List[Tuple[str, int, str]] = []
    core_dir = root / "core"
    for path in core_dir.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        module_path = _module_path_for_file(root, path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name.startswith(BANNED_PREFIXES):
                        violations.append((str(path), node.lineno, name))
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                resolved = _resolve_import(module_path, module, node.level)
                for prefix in BANNED_PREFIXES:
                    if resolved.startswith(prefix) and resolved != "":
                        violations.append((str(path), node.lineno, resolved))
                        break
    return violations


def check_core_imports(root: Path) -> Tuple[bool, str]:
    violations = scan_core_imports(root)
    if not violations:
        return True, "OK: R1 dependency rule дотримано"
    lines: Sequence[str] = [f"{path}:{line} → {name}" for path, line, name in violations]
    message = "R1 порушено: core імпортує заборонені модулі:\n" + "\n".join(lines)
    return False, message


def run() -> Tuple[bool, str]:
    return check_core_imports(repo_root())
