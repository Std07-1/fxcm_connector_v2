from __future__ import annotations

from pathlib import Path

from tools.exit_gates.gates.gate_tools_thin_wrapper import check_tools_thin_wrapper


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_tools_thin_wrapper_pass(tmp_path: Path) -> None:
    _write(tmp_path / "runtime" / "replay_ticks.py", "def main():\n    pass\n")
    content = "import runtime.replay_ticks\n" "def main():\n" "    runtime.replay_ticks.main()\n"
    _write(tmp_path / "tools" / "replay_ticks.py", content)
    ok, _ = check_tools_thin_wrapper(tmp_path)
    assert ok is True


def test_tools_thin_wrapper_fail(tmp_path: Path) -> None:
    _write(tmp_path / "runtime" / "replay_ticks.py", "def main():\n    pass\n")
    content = "import runtime.replay_ticks\n" "def process_ticks():\n" "    pass\n"
    _write(tmp_path / "tools" / "replay_ticks.py", content)
    ok, message = check_tools_thin_wrapper(tmp_path)
    assert ok is False
    assert "R3 порушено" in message
