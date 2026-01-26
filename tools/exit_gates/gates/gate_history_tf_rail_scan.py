from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Tuple


class _Visitor(ast.NodeVisitor):
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.violations: List[Tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        name = None
        if isinstance(node.func, ast.Attribute):
            name = node.func.attr
        elif isinstance(node.func, ast.Name):
            name = node.func.id
        if name == "fetch_history":
            tf_value = None
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                tf_value = node.args[1].value
            for kw in node.keywords:
                if kw.arg == "tf" and isinstance(kw.value, ast.Constant):
                    tf_value = kw.value.value
            if isinstance(tf_value, str) and tf_value != "1m":
                self.violations.append((node.lineno, tf_value))
        self.generic_visit(node)


def _scan_py(path: Path) -> List[Tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    visitor = _Visitor(str(path))
    visitor.visit(tree)
    return visitor.violations


def run() -> Tuple[bool, str]:
    root = Path(__file__).resolve().parents[3]
    targets = [root / "runtime", root / "fxcm"]
    violations: List[str] = []
    for base in targets:
        for path in base.rglob("*.py"):
            for line, tf in _scan_py(path):
                rel = path.relative_to(root)
                violations.append(f"{rel}:{line} tf={tf}")
    if violations:
        return False, "TF rail порушено: " + "; ".join(violations)
    return True, "OK: history TF rail (1m only)"
