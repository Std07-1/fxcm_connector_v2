from __future__ import annotations

from tools.exit_gates.gates import gate_ui_gap_visualization_scan


def test_gate_ui_gap_visualization_scan_ok() -> None:
    ok, message = gate_ui_gap_visualization_scan.run()
    assert ok, message
