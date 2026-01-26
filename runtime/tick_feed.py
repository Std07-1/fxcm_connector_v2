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
            self.status.record_tick_error()
            raise
