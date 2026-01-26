from __future__ import annotations

from pathlib import Path
from typing import Optional

from prometheus_client import CollectorRegistry

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from observability.metrics import create_metrics
from runtime.no_mix import NoMixDetector
from runtime.status import StatusManager


class InMemoryPublisher:
    def __init__(self) -> None:
        self.last_snapshot: Optional[str] = None
        self.last_channel: Optional[str] = None

    def set_snapshot(self, key: str, json_str: str) -> None:
        self.last_snapshot = json_str

    def publish(self, channel: str, json_str: str) -> None:
        self.last_channel = channel


def test_no_mix_detects_conflict() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    config = Config()
    calendar = Calendar([], config.calendar_tag)
    metrics = create_metrics(CollectorRegistry())
    publisher = InMemoryPublisher()
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=publisher,
        calendar=calendar,
        metrics=metrics,
    )
    status.build_initial_snapshot()

    detector = NoMixDetector()

    payload_a = {
        "symbol": "XAUUSD",
        "tf": "1m",
        "source": "history",
        "bars": [{"open_time": 1000, "complete": True}],
    }
    payload_b = {
        "symbol": "XAUUSD",
        "tf": "1m",
        "source": "history_alt",
        "bars": [{"open_time": 1000, "complete": True}],
    }

    ok_first = detector.check_final_payload(payload_a, status)
    ok_second = detector.check_final_payload(payload_b, status)

    assert ok_first is True
    assert ok_second is False

    snapshot = status.snapshot()
    assert snapshot["no_mix"]["conflicts_total"] == 1
    assert any(err["code"] == "no_mix_final_source_conflict" for err in snapshot["errors"])
