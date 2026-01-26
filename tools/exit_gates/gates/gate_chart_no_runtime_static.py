from __future__ import annotations

from typing import Tuple

from core.fixtures_path import repo_root

FORBIDDEN_LITERALS = ["runtime/static", "static/chart.html", "chart.html"]


def run() -> Tuple[bool, str]:
    path = repo_root() / "runtime" / "http_server.py"
    if not path.exists():
        return False, "FAIL: runtime/http_server.py не знайдено"
    content = path.read_text(encoding="utf-8")
    for literal in FORBIDDEN_LITERALS:
        if literal in content:
            return False, f"FAIL: знайдено заборонений літерал {literal}"
    return True, "OK: /chart не читає runtime/static"
