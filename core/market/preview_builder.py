from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

from typing_extensions import Protocol

from config.config import Config
from core.time.buckets import TF_TO_MS, get_bucket_close_ms, get_bucket_open_ms


class PreviewRail(Protocol):
    def record_ohlcv_preview_rail(
        self,
        tf: str,
        last_tick_ts_ms: int,
        last_bucket_open_ms: int,
        late_ticks_dropped_total: int,
        misaligned_open_time_total: int,
        past_mutations_total: int,
        last_late_tick: Dict[str, int],
    ) -> None: ...


@dataclass
class OhlcvBar:
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int

    def to_dict(self, source: str, complete: bool, synthetic: bool) -> Dict[str, Any]:
        return {
            "open_time": self.open_time,
            "close_time": self.close_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "tick_count": self.tick_count,
            "complete": complete,
            "synthetic": synthetic,
            "source": source,
        }


@dataclass
class OhlcvCache:
    """In-memory кеш preview барів для /api/ohlcv."""

    maxlen: int = 2000
    _store: Dict[Tuple[str, str], Deque[Dict[str, Any]]] = field(default_factory=dict)

    def update_bar(self, symbol: str, tf: str, bar: Dict[str, Any]) -> None:
        key = (symbol, tf)
        if key not in self._store:
            self._store[key] = deque(maxlen=self.maxlen)
        bars = self._store[key]
        for idx, existing in enumerate(bars):
            if existing.get("open_time") == bar.get("open_time"):
                bars[idx] = bar
                return
        bars.append(bar)

    def get_tail(self, symbol: str, tf: str, limit: int) -> List[Dict[str, Any]]:
        key = (symbol, tf)
        bars = self._store.get(key, deque())
        if limit <= 0:
            return []
        return list(bars)[-limit:]


@dataclass
class PreviewStreamState:
    current_bucket_open_ms: Optional[int] = None
    late_ticks_dropped_total: int = 0
    misaligned_open_time_total: int = 0
    past_mutations_total: int = 0
    last_tick_ts_ms: int = 0
    last_bucket_open_ms: int = 0
    last_late_tick: Dict[str, int] = field(default_factory=dict)


@dataclass
class PreviewBuilder:
    """Інкрементальний preview builder з tick -> TF бари."""

    config: Config
    cache: OhlcvCache
    status: Optional[PreviewRail] = None
    last_publish_ms: int = 0
    _current_bars: Dict[Tuple[str, str], OhlcvBar] = field(default_factory=dict)
    _stream_state: Dict[Tuple[str, str], PreviewStreamState] = field(default_factory=dict)

    def on_tick(self, symbol: str, mid: float, tick_ts_ms: int) -> None:
        for tf in self.config.ohlcv_preview_tfs:
            size = TF_TO_MS.get(tf)
            if size is None:
                continue
            if tf == "1d":
                bucket_start = get_bucket_open_ms(tf, int(tick_ts_ms), self.config.trading_day_boundary_utc)
            else:
                bucket_start = int(tick_ts_ms) // size * size
            if tf != "1d" and bucket_start % size != 0:
                state = self._get_stream_state(symbol, tf)
                state.misaligned_open_time_total += 1
                state.last_tick_ts_ms = int(tick_ts_ms)
                state.last_bucket_open_ms = int(bucket_start)
                self._sync_preview_rail(tf, state)
                continue
            state = self._get_stream_state(symbol, tf)
            state.last_tick_ts_ms = int(tick_ts_ms)
            state.last_bucket_open_ms = int(bucket_start)
            if state.current_bucket_open_ms is None:
                state.current_bucket_open_ms = int(bucket_start)
            if int(bucket_start) < int(state.current_bucket_open_ms):
                state.late_ticks_dropped_total += 1
                state.past_mutations_total += 1
                state.last_late_tick = {
                    "tick_ts_ms": int(tick_ts_ms),
                    "bucket_open_ms": int(bucket_start),
                    "current_bucket_open_ms": int(state.current_bucket_open_ms),
                }
                self._sync_preview_rail(tf, state)
                continue
            bucket_close = get_bucket_close_ms(tf, bucket_start, self.config.trading_day_boundary_utc)
            key = (symbol, tf)
            current = self._current_bars.get(key)
            if current is None or current.open_time != bucket_start:
                if current is not None:
                    final_bar = current.to_dict(source="stream", complete=False, synthetic=False)
                    self.cache.update_bar(symbol, tf, final_bar)
                if int(bucket_start) > int(state.current_bucket_open_ms):
                    state.current_bucket_open_ms = int(bucket_start)
                bar = OhlcvBar(
                    open_time=bucket_start,
                    close_time=bucket_close,
                    open=mid,
                    high=mid,
                    low=mid,
                    close=mid,
                    volume=1.0,
                    tick_count=1,
                )
                self._current_bars[key] = bar
            else:
                current.high = max(current.high, mid)
                current.low = min(current.low, mid)
                current.close = mid
                current.volume += 1.0
                current.tick_count += 1
            bar = self._current_bars[key]
            bar_dict = bar.to_dict(source="stream", complete=False, synthetic=False)
            self.cache.update_bar(symbol, tf, bar_dict)
            self._sync_preview_rail(tf, state)

    def build_payloads(self, symbol: str, limit: int) -> List[Dict[str, Any]]:
        payloads: List[Dict[str, Any]] = []
        for tf in self.config.ohlcv_preview_tfs:
            bars = self.cache.get_tail(symbol, tf, limit)
            if not bars:
                continue
            sorted_bars = sorted(bars, key=lambda b: int(b.get("open_time", 0)))
            payloads.append(
                {
                    "symbol": symbol,
                    "tf": tf,
                    "source": "stream",
                    "complete": False,
                    "synthetic": False,
                    "bars": sorted_bars,
                }
            )
        return payloads

    def should_publish(self, now_ms: int) -> bool:
        if not self.config.ohlcv_preview_enabled:
            return False
        return now_ms - self.last_publish_ms >= self.config.ohlcv_preview_publish_interval_ms

    def mark_published(self, now_ms: int) -> None:
        self.last_publish_ms = now_ms

    def _get_stream_state(self, symbol: str, tf: str) -> PreviewStreamState:
        key = (symbol, tf)
        state = self._stream_state.get(key)
        if state is None:
            state = PreviewStreamState()
            self._stream_state[key] = state
        return state

    def get_stream_state(self, symbol: str, tf: str) -> Optional[PreviewStreamState]:
        return self._stream_state.get((symbol, tf))

    def _sync_preview_rail(self, tf: str, state: PreviewStreamState) -> None:
        if self.status is None:
            return
        self.status.record_ohlcv_preview_rail(
            tf=tf,
            last_tick_ts_ms=int(state.last_tick_ts_ms),
            last_bucket_open_ms=int(state.last_bucket_open_ms),
            late_ticks_dropped_total=int(state.late_ticks_dropped_total),
            misaligned_open_time_total=int(state.misaligned_open_time_total),
            past_mutations_total=int(state.past_mutations_total),
            last_late_tick=dict(state.last_late_tick),
        )
