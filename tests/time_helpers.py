from __future__ import annotations

import time
from datetime import datetime, timezone

from core.time.timestamps import to_epoch_ms_utc

TEST_NOW_MS = to_epoch_ms_utc(datetime(2026, 1, 20, 17, 0, tzinfo=timezone.utc))
TEST_NOW_S = TEST_NOW_MS / 1000.0


def freeze_time(monkeypatch) -> None:
    """Фіксує time.time() для детермінованих тестів."""
    monkeypatch.setattr(time, "time", lambda: TEST_NOW_S)
