from __future__ import annotations

from pathlib import Path
from typing import Tuple

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager


class _DummyRedis:
    def publish(self, channel: str, payload: str) -> None:
        _ = channel
        _ = payload

    def set(self, key: str, value: str) -> None:
        _ = key
        _ = value


def run() -> Tuple[bool, str]:
    root_dir = Path(__file__).resolve().parents[3]
    config = Config()
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    validator = SchemaValidator(root_dir=root_dir)
    publisher = RedisPublisher(_DummyRedis(), config)
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=publisher,
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    status.record_tick(tick_ts_ms=2_000, snap_ts_ms=1_000, now_ms=1_000)
    snapshot = status.snapshot()
    price = snapshot.get("price", {})
    degraded = snapshot.get("degraded", [])
    errors = snapshot.get("errors", [])

    if int(price.get("tick_skew_ms", -1)) < 0:
        return False, "tick_skew_ms < 0"
    if "tick_skew_negative" not in degraded:
        return False, "очікував degraded tick_skew_negative"
    if not any(err.get("code") == "tick_skew_negative" for err in errors if isinstance(err, dict)):
        return False, "очікував errors[].code=tick_skew_negative"
    return True, "OK: tick_skew_ms не від’ємний і loud"
