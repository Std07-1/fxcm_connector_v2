from __future__ import annotations

from pathlib import Path
from typing import Tuple


def run() -> Tuple[bool, str]:
    root = Path(__file__).resolve().parents[3]
    path = root / "docs" / "runbooks" / "redis_acl.md"
    if not path.exists():
        return False, "Не знайдено docs/runbooks/redis_acl.md"
    text = path.read_text(encoding="utf-8")
    required = [
        "Runbook: Redis ACL",
        "UI користувач",
        "SMC користувач",
        "connector користувач",
        "ACL LIST",
        "PUBSUB CHANNELS",
        "NUMSUB",
    ]
    for key in required:
        if key not in text:
            return False, f"Відсутня секція: {key}"
    return True, "OK: redis_acl runbook існує"
