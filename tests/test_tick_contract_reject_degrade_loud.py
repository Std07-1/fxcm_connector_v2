from __future__ import annotations

from pathlib import Path

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from observability.metrics import create_metrics
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager
from runtime.tick_feed import TickPublisher


class _DummyRedis:
    def publish(self, channel: str, payload: str) -> None:
        return None

    def set(self, key: str, value: str) -> None:
        return None


def test_tick_contract_reject_degrade_loud() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    config = Config(tick_mode="fxcm")
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    publisher = RedisPublisher(_DummyRedis(), config)
    metrics = create_metrics()
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=publisher,
        calendar=calendar,
        metrics=metrics,
    )
    status.build_initial_snapshot()

    tick_publisher = TickPublisher(
        config=config,
        publisher=publisher,
        validator=validator,
        status=status,
        metrics=metrics,
    )

    tick_publisher.publish_tick(
        symbol="XAUUSD",
        bid=1.0,
        ask=1.2,
        mid=1.1,
        tick_ts_ms="bad",  # type: ignore[arg-type]
        snap_ts_ms=0,
    )

    snapshot = status.snapshot()
    errors = snapshot.get("errors", [])
    degraded = snapshot.get("degraded", [])
    price = snapshot.get("price", {})
    fxcm = snapshot.get("fxcm", {})

    assert any(err.get("code") == "tick_contract_error" for err in errors)
    assert "tick_contract_error" in degraded
    assert int(price.get("tick_err_total", 0)) == 1
    assert int(fxcm.get("contract_reject_total", 0)) == 1
