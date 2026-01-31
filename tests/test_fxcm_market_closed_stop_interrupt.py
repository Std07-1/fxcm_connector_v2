from __future__ import annotations

import time
from typing import Any, Dict, Optional

import pytest

from config.config import Config
from runtime.fxcm_forexconnect import FxcmForexConnectStream


class _FakeCalendar:
    def is_open(self, ts_ms: int, symbol: Optional[str] = None) -> bool:
        return False

    def next_open_ms(self, ts_ms: int, symbol: Optional[str] = None) -> int:
        return int(ts_ms + 60_000)


class _DummyStatus:
    def __init__(self) -> None:
        self.calendar = _FakeCalendar()
        self.fxcm_state: Dict[str, Any] = {}

    def clear_degraded(self, _tag: str) -> None:
        return None

    def update_fxcm_state(
        self,
        state: str,
        last_tick_ts_ms: int,
        last_err: Optional[str],
        last_ok_ts_ms: Optional[int] = None,
        reconnect_attempt: Optional[int] = None,
        next_retry_ts_ms: Optional[int] = None,
        **_extra: Any,
    ) -> None:
        self.fxcm_state = {
            "state": state,
            "last_tick_ts_ms": last_tick_ts_ms,
            "last_err": last_err,
            "last_ok_ts_ms": last_ok_ts_ms or 0,
            "reconnect_attempt": reconnect_attempt or 0,
            "next_retry_ts_ms": next_retry_ts_ms or 0,
        }

    def publish_snapshot(self) -> None:
        return None

    def append_error(
        self,
        code: str,
        severity: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        _ = (code, severity, message, context)

    def mark_degraded(self, _tag: str) -> None:
        return None


def test_fxcm_market_closed_stop_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_try_import() -> tuple[object, None]:
        return object, None

    monkeypatch.setattr("runtime.fxcm_forexconnect._try_import_forexconnect", _fake_try_import)
    monkeypatch.setattr("runtime.fxcm_forexconnect.ensure_fxcm_ready", lambda *_args, **_kwargs: True)

    status = _DummyStatus()
    config = Config()
    stream = FxcmForexConnectStream(config=config, status=status, on_tick=lambda *_: None)  # type: ignore[arg-type]

    handle = stream.start()
    assert handle is not None

    deadline = time.time() + 1.0
    while time.time() < deadline:
        if status.fxcm_state.get("state") == "paused_market_closed":
            break
        time.sleep(0.05)

    assert status.fxcm_state.get("state") == "paused_market_closed"

    start = time.time()
    stream.stop()
    elapsed = time.time() - start

    assert elapsed <= 1.0
