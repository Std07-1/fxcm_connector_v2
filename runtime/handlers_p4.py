from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

from config.config import Config
from core.validation.validator import ContractError, SchemaValidator
from observability.metrics import Metrics
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager
from store.bars_store import BarsStoreSQLite
from store.derived_builder import DerivedBuilder


def rebuild_derived_range(
    symbol: str,
    start_ms: int,
    end_ms: int,
    tfs: List[str],
    config: Config,
    bars_store: BarsStoreSQLite,
    publisher: RedisPublisher,
    validator: SchemaValidator,
    status: StatusManager,
    metrics: Optional[Metrics],
) -> None:
    """Побудова HTF final у межах діапазону."""
    if not symbol:
        raise ValueError("symbol є обов'язковим")
    if start_ms <= 0 or end_ms <= 0 or start_ms > end_ms:
        raise ValueError("Некоректний діапазон часу")
    if not tfs:
        raise ValueError("tfs має бути list[str]")

    status.record_derived_rebuild(
        state="running",
        start_ms=start_ms,
        end_ms=end_ms,
        tfs=[str(tf) for tf in tfs],
        last_error=None,
    )

    builder = DerivedBuilder(
        bars_store=bars_store,
        trading_day_boundary_utc=config.trading_day_boundary_utc,
    )

    try:
        last_ok_close_ms = 0
        lookback_days = max(1, int(math.ceil(float(end_ms - start_ms + 1) / (24 * 60 * 60 * 1000))))
        for tf in tfs:
            tf_str = str(tf)
            bars = builder.build_range(symbol=symbol, tf=tf_str, start_ms=start_ms, end_ms=end_ms)
            if not bars:
                raise ValueError("Немає повних HTF bar для tf=" + tf_str)
            publisher.publish_ohlcv_final_htf(
                symbol=symbol,
                tf=tf_str,
                bars=bars,
                validator=validator,
            )
            last_ok_close_ms = int(bars[-1]["close_time"])
            status.record_final_publish(
                last_complete_bar_ms=last_ok_close_ms,
                now_ms=int(time.time() * 1000),
                lookback_days=lookback_days,
                tf=tf_str,
            )
            if metrics is not None:
                metrics.derived_rebuild_runs_total.labels(tf=tf_str).inc()

        status.record_derived_rebuild(
            state="ok",
            start_ms=start_ms,
            end_ms=end_ms,
            tfs=[str(tf) for tf in tfs],
            last_error=None,
        )
        status.publish_snapshot()
    except (ContractError, ValueError) as exc:
        status.append_error(
            code="derived_rebuild_error",
            severity="error",
            message=str(exc),
            context={"symbol": symbol},
        )
        status.record_derived_rebuild(
            state="error",
            start_ms=start_ms,
            end_ms=end_ms,
            tfs=[str(tf) for tf in tfs],
            last_error=str(exc),
        )
        status.publish_snapshot()
        raise


def handle_rebuild_derived_command(
    payload: Dict[str, Any],
    config: Config,
    bars_store: BarsStoreSQLite,
    publisher: RedisPublisher,
    validator: SchemaValidator,
    status: StatusManager,
    metrics: Optional[Metrics],
) -> None:
    """P4: rebuild HTF final з SSOT 1m final (history_agg)."""
    args = payload.get("args", {}) if isinstance(payload, dict) else {}
    symbol = str(args.get("symbol", ""))
    if not symbol:
        raise ValueError("symbol є обов'язковим")
    window_hours = int(args.get("window_hours", config.derived_rebuild_window_hours_default))
    tfs = args.get("tfs", config.derived_rebuild_default_tfs)
    if isinstance(tfs, str):
        tfs = [tfs]
    if not isinstance(tfs, list) or not tfs:
        raise ValueError("tfs має бути list[str]")

    end_ms = bars_store.get_last_complete_close_ms(symbol, "1m")
    if end_ms <= 0:
        raise ValueError("SSOT 1m final порожній")
    start_ms = end_ms - window_hours * 60 * 60 * 1000 + 1

    rebuild_derived_range(
        symbol=symbol,
        start_ms=start_ms,
        end_ms=end_ms,
        tfs=[str(tf) for tf in tfs],
        config=config,
        bars_store=bars_store,
        publisher=publisher,
        validator=validator,
        status=status,
        metrics=metrics,
    )
