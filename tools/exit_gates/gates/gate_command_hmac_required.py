from __future__ import annotations

from pathlib import Path
from typing import Tuple


def run() -> Tuple[bool, str]:
    root = Path(__file__).resolve().parents[3]
    config_path = root / "config" / "config.py"
    command_bus_path = root / "runtime" / "command_bus.py"
    auth_path = root / "runtime" / "command_auth.py"
    schema_path = root / "core" / "contracts" / "public" / "commands_v1.json"

    if not config_path.exists():
        return False, "Не знайдено config/config.py"
    if not command_bus_path.exists():
        return False, "Не знайдено runtime/command_bus.py"
    if not auth_path.exists():
        return False, "Не знайдено runtime/command_auth.py"
    if not schema_path.exists():
        return False, "Не знайдено core/contracts/public/commands_v1.json"

    config_text = config_path.read_text(encoding="utf-8")
    for key in [
        "command_auth_enable",
        "command_auth_required",
        "command_auth_max_skew_ms",
        "command_auth_replay_ttl_ms",
    ]:
        if key not in config_text:
            return False, f"Не знайдено {key} у config"

    bus_text = command_bus_path.read_text(encoding="utf-8")
    if "verify_command_auth" not in bus_text:
        return False, "Не знайдено verify_command_auth у command_bus"
    if "auth_failed" not in bus_text:
        return False, "Не знайдено code=auth_failed у command_bus"

    schema_text = schema_path.read_text(encoding="utf-8")
    if '"auth"' not in schema_text:
        return False, "Не знайдено auth у commands_v1 schema"

    return True, "OK: command hmac required rails"
