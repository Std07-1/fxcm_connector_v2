from __future__ import annotations

import json
from pathlib import Path


def test_exit_gates_runner_policy() -> None:
    root = Path(__file__).resolve().parents[1]
    runner = root / "tools" / "run_exit_gates.py"
    assert runner.exists()

    manifest_path = root / "tools" / "exit_gates" / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ids = {item["id"] for item in manifest}
    assert {
        "gate_python_version",
        "gate_xor_mode_scan",
        "gate_no_duplicate_gate_runners",
        "gate_no_runtime_sims",
        "gate_tick_units",
        "gate_preview_1m_boundaries",
        "gate_preview_1m_geom",
        "gate_fxcm_fsm_unit",
        "gate_tick_fixtures_schema",
    }.issubset(ids)

    allowed_wrappers = {
        "gate_calendar_gaps.py",
        "gate_final_wire.py",
        "gate_no_mix.py",
        "gate_republish_watermark.py",
    }
    forbidden = [
        "tools/run_exit_gates_*.py",
        "tools/*exit*gates*.py",
        "tools/exit_gates/*runner*.py",
    ]
    for pattern in forbidden:
        matches = [p for p in root.rglob(pattern) if p.name != "run_exit_gates.py" and p.name not in allowed_wrappers]
        assert not matches
