from __future__ import annotations

import json

from core.fixtures_path import fixture_path


def test_replay_ticks_parses_jsonl_fixture() -> None:
    sample = fixture_path("ticks_sample.jsonl")
    lines = [line for line in sample.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    for line in lines:
        payload = json.loads(line)
        assert isinstance(payload.get("tick_ts_ms"), int)
        assert isinstance(payload.get("snap_ts_ms"), int)
        assert payload.get("tick_ts_ms") >= 1_000_000_000_000
        assert payload.get("snap_ts_ms") >= 1_000_000_000_000
