from __future__ import annotations

from pathlib import Path

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager
from runtime.tick_feed import TickPublisher
from tests.fixtures.sim.tick_simulator import TickSimulator


class _DummyRedis:
    def publish(self, channel: str, payload: str) -> None:
        return None

    def set(self, key: str, value: str) -> None:
        return None


def test_tick_simulator_emits_valid_tick() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    config = Config(tick_mode="sim", tick_sim_interval_ms=0)
    calendar = Calendar(
        closed_intervals_utc=config.closed_intervals_utc,
        calendar_tag=config.calendar_tag,
    )
    redis_client = _DummyRedis()
    publisher = RedisPublisher(redis_client, config)
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=publisher,
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()
    tick_publisher = TickPublisher(
        config=config,
        publisher=publisher,
        validator=validator,
        status=status,
    )
    sim = TickSimulator(config=config, publisher=tick_publisher, status=status)
    payload = sim.maybe_emit(now_ms=1_736_980_000_000)
    assert payload is not None
    validator.validate_tick_v1(payload)
