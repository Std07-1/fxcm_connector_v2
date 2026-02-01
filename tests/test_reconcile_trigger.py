from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.composition import _publish_reconcile_command
from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.status import StatusManager


class DummyRedis:
    def __init__(self) -> None:
        self.published = []

    def publish(self, channel: str, json_str: str) -> None:
        self.published.append((channel, json_str))


class InMemoryPublisher:
    def __init__(self) -> None:
        self.last_snapshot: Optional[str] = None
        self.last_channel: Optional[str] = None

    def set_snapshot(self, key: str, json_str: str) -> None:
        self.last_snapshot = json_str

    def publish(self, channel: str, json_str: str) -> None:
        self.last_channel = channel


def test_15m_boundary_emits_reconcile_command_once() -> None:
    config = Config(reconcile_enable=True)
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=InMemoryPublisher(),
        calendar=calendar,
        metrics=None,
    )
    status.build_initial_snapshot()

    redis_client = DummyRedis()
    base = 1_700_000_000_000
    base -= base % 900_000
    end_ms = int(base + 900_000 - 1)

    published_first = _publish_reconcile_command(
        redis_client=redis_client,
        config=config,
        validator=validator,
        status=status,
        end_ms=end_ms,
    )
    published_second = _publish_reconcile_command(
        redis_client=redis_client,
        config=config,
        validator=validator,
        status=status,
        end_ms=end_ms,
    )

    assert published_first is True
    assert published_second is False
    assert len(redis_client.published) == 1
    assert status.get_reconcile_last_end_ms() == end_ms
