from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from runtime.status import StatusManager


class NoMixDetector:
    """Детектор змішаних FINAL-джерел для одного бару."""

    def __init__(self) -> None:
        self._seen: Dict[Tuple[str, str, int], str] = {}

    def check_final_payload(self, payload: Dict[str, Any], status: StatusManager) -> bool:
        symbol = str(payload.get("symbol", ""))
        tf = str(payload.get("tf", ""))
        source = str(payload.get("source", "unknown"))
        bars = payload.get("bars", [])
        if not symbol or not tf or not isinstance(bars, list):
            return True
        for bar in bars:
            if not self._is_final_bar(bar, payload):
                continue
            open_time = self._open_time_ms(bar)
            if open_time is None:
                continue
            key = (symbol, tf, open_time)
            prev = self._seen.get(key)
            if prev is None:
                self._seen[key] = self._bar_source(bar, source)
                continue
            current = self._bar_source(bar, source)
            if prev != current:
                status.record_no_mix_conflict(symbol, tf, f"Final source conflict: {prev} vs {current}")
                status.append_error(
                    code="no_mix_final_source_conflict",
                    severity="error",
                    message="Конфлікт FINAL-джерел для одного бару",
                    context={
                        "symbol": symbol,
                        "tf": tf,
                        "open_time": open_time,
                        "src_a": prev,
                        "src_b": current,
                    },
                )
                return False
        return True

    @staticmethod
    def _open_time_ms(bar: Dict[str, Any]) -> Optional[int]:
        if "open_time" in bar:
            open_time = bar.get("open_time")
            if open_time is None:
                return None
            return int(open_time)
        if "open_time_ms" in bar:
            open_time_ms = bar.get("open_time_ms")
            if open_time_ms is None:
                return None
            return int(open_time_ms)
        return None

    @staticmethod
    def _bar_source(bar: Dict[str, Any], default_source: str) -> str:
        return str(bar.get("source", default_source))

    @staticmethod
    def _is_final_bar(bar: Dict[str, Any], payload: Dict[str, Any]) -> bool:
        complete = bar.get("complete")
        if complete is None:
            complete = payload.get("complete", True)
        return bool(complete is True)
