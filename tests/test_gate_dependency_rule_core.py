from __future__ import annotations

from pathlib import Path

from tools.exit_gates.gates.gate_dependency_rule_core import check_core_imports


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_dependency_rule_core_pass(tmp_path: Path) -> None:
    _write(tmp_path / "core" / "a.py", "import core.time.calendar\n")
    ok, _ = check_core_imports(tmp_path)
    assert ok is True


def test_dependency_rule_core_fail(tmp_path: Path) -> None:
    _write(tmp_path / "core" / "a.py", "import runtime.status\n")
    ok, message = check_core_imports(tmp_path)
    assert ok is False
    assert "runtime.status" in message
