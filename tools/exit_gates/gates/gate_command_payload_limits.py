from __future__ import annotations

from pathlib import Path
from typing import Tuple


def run() -> Tuple[bool, str]:
    root = Path(__file__).resolve().parents[3]
    config_path = root / "config" / "config.py"
    command_bus_path = root / "runtime" / "command_bus.py"
    metrics_path = root / "observability" / "metrics.py"

    if not config_path.exists():
        return False, "Не знайдено config/config.py"
    if not command_bus_path.exists():
        return False, "Не знайдено runtime/command_bus.py"
    if not metrics_path.exists():
        return False, "Не знайдено observability/metrics.py"

    config_text = config_path.read_text(encoding="utf-8")
    if "max_command_payload_bytes" not in config_text:
        return False, "Не знайдено max_command_payload_bytes у config"

    bus_text = command_bus_path.read_text(encoding="utf-8")
    if "max_command_payload_bytes" not in bus_text:
        return False, "Не знайдено payload limit у command_bus"
    if "command_payload_too_large" not in bus_text:
        return False, "Не знайдено code=command_payload_too_large у command_bus"
    if "commands_dropped_total" not in bus_text:
        return False, "Не знайдено лічильник commands_dropped_total у command_bus"

    metrics_text = metrics_path.read_text(encoding="utf-8")
    if "commands_dropped_total" not in metrics_text:
        return False, "Не знайдено commands_dropped_total у metrics"

    return True, "OK: payload limits для commands"
