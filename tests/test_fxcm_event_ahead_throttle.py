from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Dict, List

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from observability.metrics import create_metrics
from runtime.fxcm_forexconnect import _offer_row_to_tick
from runtime.status import StatusManager


class _FakePublisher:
    def __init__(self) -> None:
        self.snapshots: List[str] = []
        self.published: List[str] = []

    def set_snapshot(self, key: str, json_str: str) -> None:
        # ім'я параметра має збігатися з PublisherProtocol ('key')
        self.snapshots.append(json_str)

    def publish(self, channel: str, json_str: str) -> None:
        # ім'я параметра має збігатися з PublisherProtocol ('channel')
        self.published.append(json_str)


class _Row:
    def __init__(self, instrument: str, bid: float, ask: float, event_ts_ms: int) -> None:
        self.instrument = instrument
        self.bid = bid
        self.ask = ask
        self.event_ts_ms = event_ts_ms


def _build_status() -> StatusManager:
    cfg = Config()
    calendar = Calendar(calendar_tag=cfg.calendar_tag, overrides_path=cfg.calendar_path)
    validator = SchemaValidator(root_dir=Path(__file__).resolve().parents[1], calendar=calendar)
    metrics = create_metrics()
    status = StatusManager(
        config=cfg,
        validator=validator,
        publisher=_FakePublisher(),
        calendar=calendar,
        metrics=metrics,
    )
    status.build_initial_snapshot()
    return status


def test_fxcm_event_ahead_throttle() -> None:
    status = _build_status()
    metrics = status.metrics
    assert metrics is not None

    base_ms = int(time.time() * 1000)
    warn_state: Dict[str, int] = {}
    warn_lock = threading.Lock()

    for i in range(100):
        receipt_ms = base_ms + i * 100
        event_ts_ms = receipt_ms + 1
        row = _Row("XAU/USD", 1.0, 1.1, event_ts_ms)
        _offer_row_to_tick(
            row=row,
            allowed_symbols=["XAUUSD"],
            receipt_ms=receipt_ms,
            status=status,
            event_ahead_warn_state=(warn_state, warn_lock),
            event_ahead_throttle_ms=60_000,
        )

    count = metrics.fxcm_event_ahead_total.labels(symbol="XAUUSD")._value.get()
    assert int(count) == 100

    errors = status.snapshot().get("errors", [])
    event_errors = [
        err for err in errors if isinstance(err, dict) and err.get("code") == "fxcm_tick_event_ahead_of_receipt"
    ]
    assert len(event_errors) <= 1
