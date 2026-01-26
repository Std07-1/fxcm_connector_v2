from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, List, Optional

from dateutil import parser as dateutil_parser, tz as dateutil_tz

from config.config import Config
from observability.metrics import Metrics
from runtime.backfill import run_backfill
from runtime.history_provider import HistoryProvider
from runtime.status import StatusManager
from runtime.warmup import run_warmup
from store.sqlite_store import SQLiteStore


def _parse_utc_ms(value: str) -> int:
    dt = dateutil_parser.isoparse(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dateutil_tz.UTC)
    return int(dt.timestamp() * 1000)


def handle_warmup_command(
    payload: Dict[str, Any],
    config: Config,
    store: SQLiteStore,
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
    rebuild_derived = bool(args.get("rebuild_derived", False))
    rebuild_tfs = args.get("rebuild_tfs")
    if rebuild_tfs is None:
        rebuild_tfs = config.derived_rebuild_default_tfs
    if isinstance(rebuild_tfs, str):
        rebuild_tfs = [rebuild_tfs]
    if not isinstance(rebuild_tfs, list) or not rebuild_tfs:
        raise ValueError("rebuild_tfs має бути list[str]")

    run_warmup(
        config=config,
        store=store,
        provider=provider,
        status=status,
        metrics=metrics,
        symbols=symbols,
        lookback_days=lookback_days,
        publish_callback=(lambda sym: publish_tail(sym, window_hours)) if publish else None,
        rebuild_derived=rebuild_derived,
        rebuild_timeframes=[str(tf) for tf in rebuild_tfs],
        rebuild_callback=rebuild_callback if rebuild_derived else None,
    )

    now_ms = int(time.time() * 1000)
    for symbol in symbols:
        try:
            status.sync_final_1m_from_store(
                store=store,
                symbol=str(symbol),
                lookback_days=lookback_days,
                now_ms=now_ms,
            )
        except ValueError as exc:
            status.append_error(
                code="warmup_empty_history",
                severity="error",
                message=str(exc),
                context={"symbol": str(symbol), "lookback_days": int(lookback_days)},
            )
            status.publish_snapshot()
            raise


def handle_backfill_command(
    payload: Dict[str, Any],
    config: Config,
    store: SQLiteStore,
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
    rebuild_tfs = args.get("rebuild_tfs")
    if rebuild_tfs is None:
        rebuild_tfs = config.derived_rebuild_default_tfs
    if isinstance(rebuild_tfs, str):
        rebuild_tfs = [rebuild_tfs]
    if not isinstance(rebuild_tfs, list) or not rebuild_tfs:
        raise ValueError("rebuild_tfs має бути list[str]")

    run_backfill(
        config=config,
        store=store,
        provider=provider,
        status=status,
        metrics=metrics,
        symbol=symbol,
        start_ms=start_ms,
        end_ms=end_ms,
        publish_callback=(lambda sym: publish_tail(sym, window_hours)) if publish else None,
        rebuild_timeframes=[str(tf) for tf in rebuild_tfs],
        rebuild_callback=rebuild_callback,
    )

    span_days = max(1, int((end_ms - start_ms + 1) / (24 * 60 * 60 * 1000)))
    status.sync_final_1m_from_store(
        store=store,
        symbol=symbol,
        lookback_days=span_days,
        now_ms=int(time.time() * 1000),
    )
