from __future__ import annotations

from pathlib import Path

from tools.exit_gates.gates.gate_preview_builder_ssot import check_preview_builder_file


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_preview_builder_ssot_pass(tmp_path: Path) -> None:
    content = "from core.market.preview_1m_builder import Preview1mBuilder\n"
    path = tmp_path / "runtime" / "preview_builder.py"
    _write(path, content)
    ok, _ = check_preview_builder_file(path)
    assert ok is True


def test_preview_builder_ssot_fail(tmp_path: Path) -> None:
    content = (
        "from core.market.preview_1m_builder import Preview1mBuilder\n"
        "def build_preview_1m():\n"
        "    open_time = 1\n"
    )
    path = tmp_path / "runtime" / "preview_builder.py"
    _write(path, content)
    ok, message = check_preview_builder_file(path)
    assert ok is False
    assert "R2 порушено" in message
