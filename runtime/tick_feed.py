from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

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

    def publish_tick(
        self,
        symbol: str,
        bid: float,
        ask: float,
        mid: float,
        tick_ts_ms: int,
        snap_ts_ms: int,
    ) -> None:
        snapshot = self.status.snapshot()
        price = snapshot.get("price") if isinstance(snapshot, dict) else None
        last_tick_ts_ms = 0
        if isinstance(price, dict):
            last_tick_ts_ms = int(price.get("last_tick_ts_ms", 0))
        if isinstance(tick_ts_ms, int) and not isinstance(tick_ts_ms, bool):
            if last_tick_ts_ms > 0 and int(tick_ts_ms) < int(last_tick_ts_ms):
                self.status.append_error(
                    code="tick_out_of_order",
                    severity="error",
                    message="tick_ts_ms менший за попередній tick",
                    context={
                        "symbol": symbol,
                        "tick_ts_ms": int(tick_ts_ms),
                        "last_tick_ts_ms": int(last_tick_ts_ms),
                        "snap_ts_ms": int(snap_ts_ms),
                    },
                )
                self.status.mark_degraded("tick_out_of_order")
                self.status.record_tick_contract_reject()
                self.status.record_fxcm_contract_reject()
                self.status.record_fxcm_tick_drop("out_of_order")
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
            self.status.record_fxcm_tick_drop("contract_error")
            return
