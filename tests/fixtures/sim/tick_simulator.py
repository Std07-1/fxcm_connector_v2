from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from config.config import Config
from core.validation.validator import ContractError
from runtime.status import StatusManager
from runtime.tick_feed import TickPublisher


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class TickSimulator:
    """Dev-only симулятор tick (P1)."""

    config: Config
    publisher: TickPublisher
    status: StatusManager

    _thread: Optional[threading.Thread] = None
    _stop_event: threading.Event = threading.Event()
    last_emit_ms: int = 0

    def start(self) -> None:
        mode = self.config.tick_mode
        if mode == "off":
            return
        if mode == "fxcm":
            self.status.append_error(
                code="tick_mode_not_supported",
                severity="error",
                message="tick_mode=fxcm не реалізовано у P1",
            )
            self.status.mark_degraded("tick_fxcm_not_implemented")
            self.status.publish_snapshot()
            return
        if mode != "sim":
            self.status.append_error(
                code="tick_mode_not_supported",
                severity="error",
                message=f"tick_mode={mode} не підтримується",
            )
            self.status.mark_degraded("tick_mode_not_supported")
            self.status.publish_snapshot()
            return

        if not self.config.tick_symbols:
            self.status.append_error(
                code="tick_sim_no_symbols",
                severity="error",
                message="tick_symbols порожній",
            )
            self.status.mark_degraded("tick_simulator")
            self.status.publish_snapshot()
            return

        self.status.mark_degraded("tick_simulator")
        self.status.publish_snapshot()
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def maybe_emit(self, now_ms: int) -> Optional[dict]:
        if self.config.tick_mode != "sim":
            return None
        if now_ms - self.last_emit_ms < self.config.tick_sim_interval_ms:
            return None
        self.last_emit_ms = now_ms
        bid = self.config.tick_sim_bid
        ask = self.config.tick_sim_ask
        mid = (bid + ask) / 2.0
        return {
            "symbol": self.config.tick_symbols[0],
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "tick_ts": int(now_ms),
            "snap_ts": int(now_ms),
        }

    def _run(self) -> None:
        while not self._stop_event.is_set():
            now_ms = _now_ms()
            payload = self.maybe_emit(now_ms)
            if payload is not None:
                try:
                    self.publisher.publish_tick(
                        symbol=str(payload["symbol"]),
                        bid=float(payload["bid"]),
                        ask=float(payload["ask"]),
                        mid=float(payload["mid"]),
                        tick_ts_ms=int(payload["tick_ts"]),
                        snap_ts_ms=int(payload["snap_ts"]),
                    )
                except ContractError:
                    pass
                self.status.publish_snapshot()
            time.sleep(max(0.01, self.config.tick_sim_interval_ms / 1000.0))
