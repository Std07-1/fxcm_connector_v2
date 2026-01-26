from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from config.config import Config
from core.validation.validator import ContractError, SchemaValidator
from observability.metrics import Metrics
from runtime.ohlcv_preview import PreviewCandleBuilder
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class OhlcvPreviewSimulator:
    """Sim-джерело preview OHLCV для P2."""

    config: Config
    builder: PreviewCandleBuilder
    publisher: RedisPublisher
    validator: SchemaValidator
    status: StatusManager
    metrics: Optional[Metrics] = None

    _thread: Optional[threading.Thread] = None
    _stop_event: threading.Event = threading.Event()
    _counter: int = 0
    _last_mid: float = 0.0

    def start(self) -> None:
        if self.config.preview_mode == "off":
            return
        if self.config.preview_mode != "sim":
            self.status.append_error(
                code="preview_mode_not_supported",
                severity="error",
                message=f"preview_mode={self.config.preview_mode} не підтримується у P2",
            )
            self.status.mark_degraded("ohlcv_preview_mode_not_supported")
            self.status.publish_snapshot()
            return
        self.status.mark_degraded("ohlcv_preview_simulator")
        self.status.publish_snapshot()
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _next_mid(self) -> float:
        self._counter += 1
        base = (self.config.tick_sim_bid + self.config.tick_sim_ask) / 2.0
        delta = (self._counter % 10) * 0.01
        self._last_mid = base + delta
        return self._last_mid

    def _run(self) -> None:
        symbol = self.config.preview_symbol
        while not self._stop_event.is_set():
            now_ms = _now_ms()
            mid = self._next_mid()
            self.builder.on_tick(symbol=symbol, mid=mid, tick_ts_ms=now_ms)
            payloads = self.builder.build_payloads(symbol=symbol, limit=self.config.max_bars_per_message)
            for payload in payloads:
                try:
                    bars = payload.get("bars", [])
                    self.publisher.publish_ohlcv_batch(
                        symbol=str(payload.get("symbol")),
                        tf=str(payload.get("tf")),
                        bars=bars,
                        source=str(payload.get("source", "stream")),
                        validator=self.validator,
                    )
                    if bars:
                        last_open = int(bars[-1]["open_time"])
                        self.status.record_ohlcv_publish(
                            tf=str(payload.get("tf")),
                            bar_open_time_ms=last_open,
                            publish_ts_ms=now_ms,
                        )
                except ContractError as exc:
                    self.status.append_error(
                        code="ohlcv_preview_contract_error",
                        severity="error",
                        message=str(exc),
                        context={"symbol": symbol, "tf": payload.get("tf")},
                    )
                    self.status.record_ohlcv_error()
                self.status.publish_snapshot()
            time.sleep(max(0.01, self.config.preview_sim_interval_ms / 1000.0))
