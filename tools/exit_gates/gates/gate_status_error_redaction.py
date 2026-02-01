from __future__ import annotations

from pathlib import Path
from typing import Tuple


def run() -> Tuple[bool, str]:
    root = Path(__file__).resolve().parents[3]
    status_path = root / "runtime" / "status.py"
    bus_path = root / "runtime" / "command_bus.py"

    if not status_path.exists():
        return False, "Не знайдено runtime/status.py"
    if not bus_path.exists():
        return False, "Не знайдено runtime/command_bus.py"

    status_text = status_path.read_text(encoding="utf-8")
    if "append_public_error" not in status_text:
        return False, "Не знайдено append_public_error у status"

    bus_text = bus_path.read_text(encoding="utf-8")
    if "append_public_error" not in bus_text:
        return False, "Не знайдено використання append_public_error у command_bus"
    if "Некоректна команда" not in bus_text:
        return False, "Не знайдено публічне повідомлення редактінгу"

    return True, "OK: redaction status.errors для команд"
