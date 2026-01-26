from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from core.validation.validator import ContractError, SchemaValidator

if TYPE_CHECKING:
    from runtime.publisher import RedisPublisher


def validate_final_bars(bars: List[Dict[str, Any]]) -> None:
    seen = set()
    last_open = None
    for bar in bars:
        open_time = int(bar["open_time"])  # type: ignore[arg-type]
        close_time = int(bar["close_time"])  # type: ignore[arg-type]
        event_ts = int(bar["event_ts"])  # type: ignore[arg-type]
        if bar.get("complete") is not True:
            raise ContractError("final bar має complete=true")
        if bar.get("synthetic") is not False:
            raise ContractError("final bar має synthetic=false")
        source = bar.get("source")
        if source not in {"history", "history_agg"}:
            raise ContractError("final bar має source=history або history_agg")
        if last_open is not None and open_time < last_open:
            raise ContractError("bars мають бути відсортовані за open_time")
        if open_time in seen:
            raise ContractError("bars містять дублі open_time")
        if event_ts != close_time:
            raise ContractError("event_ts має дорівнювати close_time")
        seen.add(open_time)
        last_open = open_time


def publish_final_1m(
    publisher: "RedisPublisher",
    validator: SchemaValidator,
    symbol: str,
    bars: List[Dict[str, Any]],
) -> None:
    validate_final_bars(bars)
    publisher.publish_ohlcv_final_1m(symbol=symbol, bars=bars, validator=validator)


def publish_final_htf(
    publisher: "RedisPublisher",
    validator: SchemaValidator,
    symbol: str,
    tf: str,
    bars: List[Dict[str, Any]],
) -> None:
    validate_final_bars(bars)
    publisher.publish_ohlcv_final_htf(symbol=symbol, tf=tf, bars=bars, validator=validator)
