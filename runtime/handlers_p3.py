from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional

from dateutil import parser as dateutil_parser, tz as dateutil_tz

from config.config import Config
from observability.metrics import Metrics
from runtime.backfill import run_backfill
from runtime.history_provider import HistoryProvider
from runtime.status import StatusManager
from runtime.warmup import run_warmup
from store.file_cache import FileCache


def _parse_utc_ms(value: str) -> int:
    dt = dateutil_parser.isoparse(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dateutil_tz.UTC)
    return int(dt.timestamp() * 1000)


def handle_warmup_command(
    payload: Dict[str, Any],
    config: Config,
    file_cache: FileCache,
    provider: HistoryProvider,
    status: StatusManager,
    metrics: Optional[Metrics],
    publish_tail: Callable[[str, int], None],
    rebuild_callback: Optional[Callable[[str, int, int, List[str]], None]] = None,
) -> None:
    args = payload.get("args", {}) if isinstance(payload, dict) else {}
    symbols = args.get("symbols", ["XAUUSD"])
    if isinstance(symbols, str):
        symbols = [symbols]
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("symbols має бути list[str] або str")
    lookback_hours = args.get("lookback_hours")
    if lookback_hours is not None:
        lookback_days = max(1, int(math.ceil(float(lookback_hours) / 24.0)))
    else:
        lookback_days = int(args.get("lookback_days", config.warmup_lookback_days))
    publish = bool(args.get("publish", True))
    window_hours = int(args.get("window_hours", 24))
    run_warmup(
        config=config,
        file_cache=file_cache,
        provider=provider,
        status=status,
        metrics=metrics,
        symbols=symbols,
        lookback_days=lookback_days,
        publish_callback=(lambda sym: publish_tail(sym, window_hours)) if publish else None,
    )


def handle_backfill_command(
    payload: Dict[str, Any],
    config: Config,
    file_cache: FileCache,
    provider: HistoryProvider,
    status: StatusManager,
    metrics: Optional[Metrics],
    publish_tail: Callable[[str, int], None],
    rebuild_callback: Optional[Callable[[str, int, int, List[str]], None]] = None,
) -> None:
    args = payload.get("args", {}) if isinstance(payload, dict) else {}
    symbol = str(args.get("symbol", ""))
    if not symbol:
        raise ValueError("symbol є обов'язковим")
    start_ms = int(args.get("start_ms", 0))
    end_ms = int(args.get("end_ms", 0))
    start_utc = args.get("start_utc")
    end_utc = args.get("end_utc")
    if start_ms <= 0 and isinstance(start_utc, str):
        start_ms = _parse_utc_ms(start_utc)
    if end_ms <= 0 and isinstance(end_utc, str):
        end_ms = _parse_utc_ms(end_utc)
    if start_ms <= 0 or end_ms <= 0 or start_ms > end_ms:
        raise ValueError("start_ms/end_ms мають бути коректними")
    publish = bool(args.get("publish", True))
    window_hours = int(args.get("window_hours", 24))
    run_backfill(
        config=config,
        file_cache=file_cache,
        provider=provider,
        status=status,
        metrics=metrics,
        symbol=symbol,
        start_ms=start_ms,
        end_ms=end_ms,
        publish_callback=(lambda sym: publish_tail(sym, window_hours)) if publish else None,
        rebuild_timeframes=None,
        rebuild_callback=None,
    )
