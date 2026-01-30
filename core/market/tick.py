from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from core.time.epoch_rails import MAX_EPOCH_MS
from core.validation.errors import ContractError


@dataclass(frozen=True)
class Tick:
    symbol: str
    bid: float
    ask: float
    mid: float
    tick_ts_ms: int
    snap_ts_ms: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "tick_ts_ms": self.tick_ts_ms,
            "snap_ts_ms": self.snap_ts_ms,
        }


def _require_int_ms(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{field} має бути int ms")
    if value < 0:
        raise ContractError(f"{field} має бути >= 0")
    if value < 1_000_000_000_000:
        raise ContractError(f"{field} має бути epoch ms (>=1e12)")
    if value > MAX_EPOCH_MS:
        raise ContractError(f"{field} має бути epoch ms (не microseconds)")
    return value


def _require_mid(bid: float, ask: float, mid: float) -> None:
    expected = (bid + ask) / 2.0
    if abs(expected - mid) > 1e-6:
        raise ContractError("mid має дорівнювати (bid+ask)/2")


def normalize_tick(symbol: str, bid: float, ask: float, tick_ts_ms: int, snap_ts_ms: int) -> Tick:
    if bid > ask:
        raise ContractError("bid має бути <= ask")
    tick_ts = _require_int_ms(tick_ts_ms, "tick_ts_ms")
    snap_ts = _require_int_ms(snap_ts_ms, "snap_ts_ms")
    if tick_ts > snap_ts:
        raise ContractError("tick_ts_ms має бути <= snap_ts_ms")
    mid = (bid + ask) / 2.0
    _require_mid(bid, ask, mid)
    return Tick(
        symbol=symbol,
        bid=float(bid),
        ask=float(ask),
        mid=float(mid),
        tick_ts_ms=tick_ts,
        snap_ts_ms=snap_ts,
    )


def tick_from_payload(payload: Dict[str, Any]) -> Tick:
    symbol = str(payload.get("symbol", ""))
    if not symbol:
        raise ContractError("symbol має бути непорожнім рядком")
    bid = payload.get("bid")
    ask = payload.get("ask")
    tick_ts_ms = payload.get("tick_ts_ms")
    if tick_ts_ms is None:
        tick_ts_ms = payload.get("tick_ts")
    snap_ts_ms = payload.get("snap_ts_ms")
    if snap_ts_ms is None:
        snap_ts_ms = payload.get("snap_ts")
    if bid is None or ask is None:
        raise ContractError("bid/ask обов'язкові")
    if tick_ts_ms is None or snap_ts_ms is None:
        raise ContractError("tick_ts_ms/snap_ts_ms обов'язкові")
    return normalize_tick(
        symbol=symbol,
        bid=float(bid),
        ask=float(ask),
        tick_ts_ms=int(tick_ts_ms),
        snap_ts_ms=int(snap_ts_ms),
    )
