from __future__ import annotations

import json
from typing import Any, Tuple

from core.fixtures_path import fixture_path
from core.validation.validator import ContractError


def _check_int_ms(value: Any, field: str) -> None:
    if not isinstance(value, int):
        raise ContractError(f"{field} має бути int")
    if value < 1_000_000_000_000:
        raise ContractError(f"{field} має бути epoch ms (>=1e12)")


def run() -> Tuple[bool, str]:
    sample = fixture_path("ticks_sample.jsonl")
    if not sample.exists():
        return False, "FAIL: ticks_sample.jsonl відсутній"

    lines = [line for line in sample.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return False, "FAIL: ticks_sample.jsonl порожній"

    count = 0
    try:
        for line in lines:
            payload = json.loads(line)
            tick_ts_ms = payload.get("tick_ts_ms")
            snap_ts_ms = payload.get("snap_ts_ms")
            _check_int_ms(tick_ts_ms, "tick_ts_ms")
            _check_int_ms(snap_ts_ms, "snap_ts_ms")
            count += 1
    except (json.JSONDecodeError, ContractError) as exc:
        return False, f"FAIL: {exc}"

    return True, f"OK: tick ts у ms enforced; checked_lines={count}"
