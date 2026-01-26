from __future__ import annotations

from pathlib import Path
from typing import Tuple


def run() -> Tuple[bool, str]:
    root = Path(__file__).resolve().parents[3]
    path = root / "runtime" / "status.py"
    if not path.exists():
        return False, "Не знайдено runtime/status.py"
    text = path.read_text(encoding="utf-8")

    if "STATUS_PUBSUB_MAX_BYTES" not in text:
        return False, "Не знайдено STATUS_PUBSUB_MAX_BYTES"
    if "status_payload_too_large" not in text:
        return False, "Не знайдено status_payload_too_large у статус rail"
    if "build_status_pubsub_payload" not in text:
        return False, "Не знайдено build_status_pubsub_payload"
    return True, "OK: status pubsub size rail"
