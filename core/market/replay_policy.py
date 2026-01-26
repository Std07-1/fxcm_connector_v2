from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Tuple

from core.time.calendar import Calendar
from core.validation.validator import ContractError, SchemaValidator


@dataclass
class TickReplayPolicy:
    """Перевірки replay ticks: schema + CLOSED policy + монотонність."""

    calendar: Calendar
    validator: SchemaValidator
    _last_by_symbol: Dict[str, Tuple[int, int]] = field(default_factory=dict)

    def validate_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.validator.validate_tick_v1(payload)
        symbol = str(payload.get("symbol", ""))
        if not symbol:
            raise ContractError("symbol має бути непорожнім рядком")
        tick_ts_raw = payload.get("tick_ts")
        snap_ts_raw = payload.get("snap_ts")
        if not isinstance(tick_ts_raw, int) or isinstance(tick_ts_raw, bool):
            raise ContractError("tick_ts має бути int ms")
        if not isinstance(snap_ts_raw, int) or isinstance(snap_ts_raw, bool):
            raise ContractError("snap_ts має бути int ms")
        tick_ts = int(tick_ts_raw)
        snap_ts = int(snap_ts_raw)
        if not self.calendar.is_open(tick_ts):
            raise ContractError("tick_ts поза trading time")
        last = self._last_by_symbol.get(symbol)
        if last is not None:
            last_tick_ts, last_snap_ts = last
            if tick_ts < last_tick_ts:
                raise ContractError("tick_ts має бути монотонним")
            if tick_ts == last_tick_ts and snap_ts < last_snap_ts:
                raise ContractError("snap_ts має бути non-decreasing при рівному tick_ts")
        self._last_by_symbol[symbol] = (tick_ts, snap_ts)
        return payload


def validate_jsonl(path: Path, policy: TickReplayPolicy) -> int:
    if not path.exists():
        raise ContractError("replay файл не знайдено")
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise ContractError("replay файл порожній")
    count = 0
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(f"replay JSONL невалідний: {exc}") from exc
        if not isinstance(payload, dict):
            raise ContractError("replay рядок має бути JSON-об'єктом")
        policy.validate_payload(payload)
        count += 1
    return count
