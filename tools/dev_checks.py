"""Кросплатформний runner для dev‑перевірок (ruff/mypy/pytest).

Використання:
  python -m tools.dev_checks
  python -m tools.dev_checks --exit-gates --manifest tools/exit_gates/manifest.json --out reports/exit_gates
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import List


def _run(cmd: List[str], label: str) -> int:
    print(f"=== {label} ===")
    print(" ".join(cmd))
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"FAIL: {label} (code={result.returncode})")
    else:
        print(f"OK: {label}")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Dev checks runner (ruff/mypy/pytest).")
    parser.add_argument("--exit-gates", action="store_true", help="Запустити exit gates через runner.")
    parser.add_argument("--manifest", default="tools/exit_gates/manifest.json", help="Шлях до manifest.json.")
    parser.add_argument("--out", default="reports/exit_gates", help="Каталог для результатів exit gates.")
    parser.add_argument("--continue", dest="cont", action="store_true", help="Не зупинятись на першій помилці.")
    args = parser.parse_args()

    py = sys.executable
    steps = [
        ([py, "-m", "ruff", "check", "."], "ruff"),
        ([py, "-m", "mypy", "."], "mypy"),
        ([py, "-m", "pytest", "-q"], "pytest"),
    ]

    for cmd, label in steps:
        code = _run(cmd, label)
        if code != 0 and not args.cont:
            return code

    if args.exit_gates:
        code = _run([py, "-m", "tools.run_exit_gates", "--out", args.out, "--manifest", args.manifest], "exit_gates")
        if code != 0:
            return code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
