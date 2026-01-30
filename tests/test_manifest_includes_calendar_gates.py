from __future__ import annotations

import json
from pathlib import Path


def test_manifest_includes_calendar_gates() -> None:
    manifest_path = Path(__file__).resolve().parents[1] / "tools" / "exit_gates" / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    gate_ids = {str(entry.get("id")) for entry in data}
    assert "gate_calendar_schedule_drift" in gate_ids
    assert "gate_calendar_closed_intervals" in gate_ids
    assert "gate_calendar_holiday_policy" in gate_ids
    assert "gate_fxcm_calendar_ssot" in gate_ids
    assert "gate_no_calendar_stub_mentions" in gate_ids
