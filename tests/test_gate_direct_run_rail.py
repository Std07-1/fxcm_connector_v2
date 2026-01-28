from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_gate_direct_run_rail() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    gate_path = repo_root / "tools" / "exit_gates" / "gates" / "gate_calendar_schedule_drift.py"
    result = subprocess.run(
        [sys.executable, str(gate_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    combined = f"{result.stdout}\n{result.stderr}"
    assert "прямий запуск gate_*.py заборонено" in combined
