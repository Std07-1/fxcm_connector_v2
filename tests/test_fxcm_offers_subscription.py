from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.time.timestamps import to_epoch_ms_utc
from observability.metrics import Metrics
from runtime.fxcm_forexconnect import _loud_offers_subscription_error, _offer_row_to_tick, _stale_action


class DummyRow:
    def __init__(self, instrument: str, bid: float, ask: float, event_time: Optional[datetime]) -> None:
        self.instrument = instrument
        self.bid = bid
        self.ask = ask
        self.time = event_time


class DummyStatus:
    def __init__(self) -> None:
        self.errors: List[Dict[str, Any]] = []
        self.degraded: List[str] = []
        self.fxcm_state: Dict[str, Any] = {}
        self.published = 0
        self.metrics: Optional[Metrics] = None

    def append_error(
        self,
        code: str,
        severity: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry: Dict[str, Any] = {"code": code, "severity": severity, "message": message}
        if context:
            entry["context"] = context
        self.errors.append(entry)

    def append_error_throttled(
        self,
        code: str,
        severity: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        throttle_key: Optional[str] = None,
        throttle_ms: int = 60_000,
        now_ms: Optional[int] = None,
        external_last_ts_by_key: Optional[Dict[str, int]] = None,
        external_lock: Optional[Any] = None,
    ) -> bool:
        _ = throttle_key
        _ = throttle_ms
        _ = now_ms
        _ = external_last_ts_by_key
        _ = external_lock
        self.append_error(code=code, severity=severity, message=message, context=context)
        return True

    def mark_degraded(self, code: str) -> None:
        self.degraded.append(code)

    def update_fxcm_state(
        self,
        state: str,
        last_tick_ts_ms: int,
        last_err: Optional[str],
        last_err_ts_ms: Optional[int] = None,
        **_extra: Any,
    ) -> None:
        self.fxcm_state = {
            "state": state,
            "last_tick_ts_ms": last_tick_ts_ms,
            "last_err": last_err,
            "last_err_ts_ms": last_err_ts_ms or 0,
        }

    def publish_snapshot(self) -> None:
        self.published += 1

    def record_tick_drop_missing_event(self, now_ms: int) -> None:
        _ = now_ms


def test_offers_listener_emits_tick() -> None:
    event_time = datetime(2026, 1, 20, 17, 0, tzinfo=timezone.utc)
    row = DummyRow("XAU/USD", 2000.0, 2000.2, event_time)
    status = DummyStatus()
    receipt_ms = int(to_epoch_ms_utc(event_time)) + 1000
    tick = _offer_row_to_tick(row, ["XAUUSD"], receipt_ms=receipt_ms, status=status)
    assert tick is not None
    assert tick.symbol == "XAUUSD"
    assert tick.bid == 2000.0
    assert tick.ask == 2000.2
    assert tick.tick_ts_ms == to_epoch_ms_utc(event_time)
    assert tick.snap_ts_ms == receipt_ms


def test_fxcm_tick_missing_event_time_is_loud_and_dropped() -> None:
    row = DummyRow("XAU/USD", 2000.0, 2000.2, None)
    status = DummyStatus()
    tick = _offer_row_to_tick(row, ["XAUUSD"], receipt_ms=1_700_000_000_000, status=status)
    assert tick is None
    assert any(err.get("code") == "missing_tick_event_ts" for err in status.errors)


def test_fxcm_tick_event_ahead_of_receipt_normalizes_snap_ts() -> None:
    event_time = datetime(2026, 1, 20, 17, 0, 2, tzinfo=timezone.utc)
    row = DummyRow("XAU/USD", 2000.0, 2000.2, event_time)
    status = DummyStatus()
    receipt_ms = int(to_epoch_ms_utc(event_time)) - 1000
    tick = _offer_row_to_tick(row, ["XAUUSD"], receipt_ms=receipt_ms, status=status)
    assert tick is not None
    assert tick.snap_ts_ms >= tick.tick_ts_ms
    assert any(err.get("code") == "fxcm_tick_event_ahead_of_receipt" for err in status.errors)


def test_stale_no_ticks_triggers_resubscribe_then_reconnect() -> None:
    action_first = _stale_action(
        last_tick_ts_ms=0,
        last_ok_ts_ms=1,
        now_ms=40_000,
        stale_ms=30_000,
        resubscribe_attempted=False,
        is_market_open=True,
    )
    action_second = _stale_action(
        last_tick_ts_ms=0,
        last_ok_ts_ms=1,
        now_ms=40_000,
        stale_ms=30_000,
        resubscribe_attempted=True,
        is_market_open=True,
    )
    assert action_first == "resubscribe"
    assert action_second == "reconnect"


def test_fxcm_preview_mode_requires_offers_subscription() -> None:
    status = DummyStatus()
    _loud_offers_subscription_error(status, err_ts=123, message="FXCM OFFERS subscription не піднято")  # type: ignore
    assert status.errors
    assert status.degraded == ["fxcm_offers_subscribe_failed"]
    assert status.fxcm_state.get("state") == "error"
    assert status.published == 1
