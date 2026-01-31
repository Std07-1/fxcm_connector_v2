from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import List

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from runtime.status import StatusManager
from ui_lite import server as ui_server


class FakePublisher:
    def __init__(self) -> None:
        self.snapshots: List[str] = []
        self.published: List[str] = []

    def set_snapshot(self, key: str, json_str: str) -> None:
        self.snapshots.append(json_str)

    def publish(self, channel: str, json_str: str) -> None:
        self.published.append(json_str)


def _make_closed_overrides(tmp_path: Path, tag: str, now_ms: int) -> Path:
    overrides = [
        {
            "calendar_tag": tag,
            "tz_name": "UTC",
            "weekly_open": "00:00",
            "weekly_close": "00:00",
            "daily_break_start": "00:00",
            "daily_break_minutes": 1,
            "closed_intervals_utc": [[int(now_ms - 60_000), int(now_ms + 60_000)]],
        }
    ]
    path = tmp_path / "calendar_overrides.json"
    path.write_text(json.dumps(overrides, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path


def test_status_heartbeat_paused_market_closed(tmp_path: Path) -> None:
    now_ms = int(time.time() * 1000)
    tag = "test_calendar_closed"
    overrides_path = _make_closed_overrides(tmp_path, tag, now_ms)
    calendar = Calendar(calendar_tag=tag, overrides_path=str(overrides_path))
    assert calendar.is_open(now_ms) is False

    config = replace(
        Config(),
        calendar_tag=tag,
        calendar_path=str(overrides_path),
        status_publish_period_ms=1000,
        status_fresh_warn_ms=3000,
    )
    validator = SchemaValidator(root_dir=Path(__file__).resolve().parents[1], calendar=calendar)
    publisher = FakePublisher()
    status = StatusManager(config=config, validator=validator, publisher=publisher, calendar=calendar)
    status.build_initial_snapshot()

    start = time.time()
    while time.time() - start < 3.5:
        status.publish_if_due(interval_ms=int(config.status_publish_period_ms))
        time.sleep(0.2)

    assert len(publisher.published) >= 2
    ts_values = [int(json.loads(item).get("ts", 0)) for item in publisher.published]
    assert max(ts_values) > min(ts_values)

    state = ui_server._STATE
    with state.lock:
        old_snapshot = dict(state.last_status_snapshot) if state.last_status_snapshot else {}
        old_status_ok = state.status_ok
        old_status_ts_ms = state.last_status_ts_ms
        old_warn_ms = state.status_fresh_warn_ms
        old_period_ms = state.status_publish_period_ms

        state.last_status_snapshot = json.loads(publisher.published[-1])
        state.status_ok = True
        state.last_status_ts_ms = ts_values[-1]
        state.status_fresh_warn_ms = int(config.status_fresh_warn_ms)
        state.status_publish_period_ms = int(config.status_publish_period_ms)

    try:
        health = ui_server._build_health_payload(ts_values[-1] + 1500)
        assert health["status_stale"] is False
    finally:
        with state.lock:
            state.last_status_snapshot = old_snapshot
            state.status_ok = old_status_ok
            state.last_status_ts_ms = old_status_ts_ms
            state.status_fresh_warn_ms = old_warn_ms
            state.status_publish_period_ms = old_period_ms
