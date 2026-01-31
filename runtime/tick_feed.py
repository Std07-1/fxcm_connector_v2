from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from config.config import Config
from core.validation.validator import ContractError, SchemaValidator
from observability.metrics import Metrics
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class TickPublisher:
    """Публікатор tick у Redis з валідацією та оновленням статусу."""

    config: Config
    publisher: RedisPublisher
    validator: SchemaValidator
    status: StatusManager
    metrics: Optional[Metrics] = None
    _last_tick_ts_by_symbol: Dict[str, int] = field(default_factory=dict)

    def publish_tick(
        self,
        symbol: str,
        bid: float,
        ask: float,
        mid: float,
        tick_ts_ms: int,
        snap_ts_ms: int,
    ) -> None:
        last_tick_ts_ms = int(self._last_tick_ts_by_symbol.get(symbol, 0))
        if isinstance(tick_ts_ms, int) and not isinstance(tick_ts_ms, bool):
            if last_tick_ts_ms > 0 and int(tick_ts_ms) < int(last_tick_ts_ms):
                bucket_open_ms = int(tick_ts_ms) // 60_000 * 60_000
                last_bucket_open_ms = int(last_tick_ts_ms) // 60_000 * 60_000
                if bucket_open_ms < last_bucket_open_ms:
                    if self.metrics is not None:
                        self.metrics.tick_out_of_order_total.labels(symbol=symbol).inc()
                    self.status.append_error_throttled(
                        code="tick_out_of_order",
                        severity="error",
                        message="tick_ts_ms менший за попередній tick (bucket назад)",
                        context={
                            "symbol": symbol,
                            "tick_ts_ms": int(tick_ts_ms),
                            "last_tick_ts_ms": int(last_tick_ts_ms),
                            "snap_ts_ms": int(snap_ts_ms),
                        },
                        throttle_key=f"tick_out_of_order:{symbol}",
                        throttle_ms=60_000,
                        now_ms=int(snap_ts_ms),
                    )
                    self.status.mark_degraded("tick_out_of_order")
                    self.status.record_tick_contract_reject()
                    self.status.record_fxcm_contract_reject()
                    return
        payload = {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "tick_ts": tick_ts_ms,
            "snap_ts": snap_ts_ms,
        }
        try:
            self.validator.validate_tick_v1(payload)
            json_str = self.publisher.json_dumps(payload)
            self.publisher.publish(self.config.ch_price_tik(), json_str)
            now_ms = _now_ms()
            self.status.record_tick(
                tick_ts_ms=int(tick_ts_ms),
                snap_ts_ms=int(snap_ts_ms),
                now_ms=now_ms,
            )
            self._last_tick_ts_by_symbol[symbol] = int(tick_ts_ms)
        except ContractError as exc:
            self.status.append_error(
                code="tick_contract_error",
                severity="error",
                message=str(exc),
                context={"symbol": symbol},
            )
            self.status.mark_degraded("tick_contract_error")
            self.status.record_tick_contract_reject()
            self.status.record_fxcm_contract_reject()
            return
