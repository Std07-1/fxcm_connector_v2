from __future__ import annotations

from pathlib import Path

import pytest

from core.validation.validator import ContractError, SchemaValidator


def test_commands_v1_valid() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    payload = {"cmd": "ping", "req_id": "r1", "ts": 1, "args": {}}
    validator.validate_commands_v1(payload)


def test_commands_v1_extra_field_rejected() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    payload = {"cmd": "ping", "req_id": "r1", "ts": 1, "args": {}, "extra": 123}
    with pytest.raises(ContractError):
        validator.validate_commands_v1(payload)
