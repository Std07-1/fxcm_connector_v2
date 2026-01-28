from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from config.config import Config
from runtime.preview_builder import OhlcvCache, PreviewBuilder
from runtime.status import StatusManager


@dataclass
class PreviewCandleBuilder:
    """Побудова preview свічок (обгортка над PreviewBuilder)."""

    config: Config
    cache: OhlcvCache
    status: Optional[StatusManager] = None
    _inner: PreviewBuilder = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._inner = PreviewBuilder(config=self.config, cache=self.cache, status=self.status)

    def on_tick(self, symbol: str, mid: float, tick_ts_ms: int) -> None:
        self._inner.on_tick(symbol=symbol, mid=mid, tick_ts_ms=tick_ts_ms)

    def build_payloads(self, symbol: str, limit: int) -> List[Dict[str, Any]]:
        return self._inner.build_payloads(symbol=symbol, limit=limit)

    def should_publish(self, now_ms: int) -> bool:
        return self._inner.should_publish(now_ms)

    def mark_published(self, now_ms: int) -> None:
        self._inner.mark_published(now_ms)


def select_closed_bars_for_archive(
    bars: List[Dict[str, Any]],
    last_archived_open_ms: int,
) -> List[Dict[str, Any]]:
    if len(bars) < 2:
        return []
    closed = []
    for bar in bars[:-1]:
        open_ms = int(bar.get("open_time", 0))
        if open_ms > int(last_archived_open_ms):
            closed.append(bar)
    return closed
