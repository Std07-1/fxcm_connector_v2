from __future__ import annotations

from typing import Tuple

from core.fixtures_path import fixture_path
from tools.validate_tick_fixtures import validate_jsonl


def run() -> Tuple[bool, str]:
    fixture = fixture_path("ticks_sample_fxcm.jsonl")
    ok, message, count = validate_jsonl(fixture)
    if not ok:
        return False, f"FAIL: {message}"
    return True, f"OK: fixtures валідні; lines={count}"
