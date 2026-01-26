from __future__ import annotations

# ruff: noqa: I001

import sys

from tools.exit_gates.gates.gate_final_wire import main


if __name__ == "__main__":
    if __package__ is None:
        print("FAIL: запускай через python -m tools.exit_gates.gate_final_wire --symbol ... --tf ...")
        sys.exit(2)
    sys.exit(main())
