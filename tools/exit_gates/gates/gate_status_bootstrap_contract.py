from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import ContractError, SchemaValidator
from runtime.status import StatusManager, build_status_pubsub_payload
from tools.run_exit_gates import fail_direct_gate_run


class InMemoryPublisher:
    def __init__(self) -> None:
        self.last_snapshot: Optional[str] = None
        self.last_channel: Optional[str] = None

    def set_snapshot(self, key: str, json_str: str) -> None:
        self.last_snapshot = json_str

    def publish(self, channel: str, json_str: str) -> None:
        self.last_channel = channel


def run() -> Tuple[bool, str]:
    config = Config()
    root_dir = Path(__file__).resolve().parents[3]
    validator = SchemaValidator(root_dir=root_dir)
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=InMemoryPublisher(),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()
    status.record_bootstrap_step(step="bootstrap", state="running")
    payload = build_status_pubsub_payload(status.snapshot())
    try:
        validator.validate_status_v2(payload)
    except ContractError as exc:
        return False, f"FAIL: {exc}"
    bootstrap = payload.get("bootstrap")
    if not isinstance(bootstrap, dict):
        return False, "FAIL: bootstrap відсутній"
    steps = bootstrap.get("steps")
    if not isinstance(steps, list):
        return False, "FAIL: bootstrap.steps не list"
    return True, "OK: bootstrap schema"


if __name__ == "__main__":
    fail_direct_gate_run("gate_status_bootstrap_contract")
