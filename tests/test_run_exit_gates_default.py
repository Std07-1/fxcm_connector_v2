from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_run_exit_gates_default_manifest(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = tmp_path / "exit_gates"
    manifest = repo_root / "tools" / "exit_gates" / "manifest.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.run_exit_gates",
            "--out",
            str(out_dir),
            "--manifest",
            str(manifest),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            "run_exit_gates повернув ненульовий код:\n" f"stdout:\n{result.stdout}\n" f"stderr:\n{result.stderr}\n"
        )
