from __future__ import annotations

from pathlib import Path
from typing import Tuple


def run() -> Tuple[bool, str]:
    root = Path(__file__).resolve().parents[3]
    config_path = root / "config" / "config.py"
    command_bus_path = root / "runtime" / "command_bus.py"
    metrics_path = root / "observability" / "metrics.py"
    test_path = root / "tests" / "test_command_bus_ratelimit.py"

    if not config_path.exists():
        return False, "Не знайдено config/config.py"
    if not command_bus_path.exists():
        return False, "Не знайдено runtime/command_bus.py"
    if not metrics_path.exists():
        return False, "Не знайдено observability/metrics.py"
    if not test_path.exists():
        return False, "Не знайдено tests/test_command_bus_ratelimit.py"

    config_text = config_path.read_text(encoding="utf-8")
    for key in [
        "command_rate_limit_enable",
        "command_rate_limit_raw_per_s",
        "command_rate_limit_cmd_per_s",
        "command_coalesce_enable",
        "command_heavy_collapse_enable",
    ]:
        if key not in config_text:
            return False, f"Не знайдено {key} у config"

    bus_text = command_bus_path.read_text(encoding="utf-8")
    if "TokenBucket" not in bus_text:
        return False, "Не знайдено TokenBucket у command_bus"
    if "rate_limited" not in bus_text:
        return False, "Не знайдено code=rate_limited у command_bus"
    if "command_collapsed" not in bus_text:
        return False, "Не знайдено code=command_collapsed у command_bus"

    metrics_text = metrics_path.read_text(encoding="utf-8")
    if "commands_rate_limited_total" not in metrics_text:
        return False, "Не знайдено commands_rate_limited_total у metrics"
    if "commands_coalesced_total" not in metrics_text:
        return False, "Не знайдено commands_coalesced_total у metrics"

    return True, "OK: command_bus rate-limit/coalesce rails"
