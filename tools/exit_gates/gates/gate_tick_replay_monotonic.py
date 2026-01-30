from __future__ import annotations

from pathlib import Path
from typing import Tuple

from core.fixtures_path import fixture_path, repo_root
from core.market.replay_policy import TickReplayPolicy, validate_jsonl
from core.time.calendar import Calendar
from core.validation.validator import ContractError, SchemaValidator


def run() -> Tuple[bool, str]:
    path = fixture_path("ticks_replay_sample.jsonl")
    if not path.exists():
        return False, "FAIL: ticks_replay_sample.jsonl відсутній"

    root_dir = repo_root()
    validator = SchemaValidator(root_dir=root_dir)
    calendar = Calendar(calendar_tag="fxcm_calendar_v1_ny")
    policy = TickReplayPolicy(calendar=calendar, validator=validator)
    try:
        count = validate_jsonl(Path(path), policy)
    except ContractError as exc:
        return False, f"FAIL: {exc}"
    return True, f"OK: replay tick монотонність/closed policy; checked_lines={count}"
