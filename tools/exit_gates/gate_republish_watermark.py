from __future__ import annotations

# ruff: noqa: I001

import sys

from tools.exit_gates.gates.gate_republish_watermark import main


if __name__ == "__main__":
    if __package__ is None:
        print("FAIL: запускай через python -m tools.exit_gates.gate_republish_watermark --symbol ... --tfs ...")
        sys.exit(2)
    sys.exit(main())
