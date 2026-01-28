from __future__ import annotations

from tools.exit_gates.gates.gate_calendar_closed_intervals import run


def test_gate_calendar_closed_intervals_ok() -> None:
    ok, message = run()
    assert ok is True, message
