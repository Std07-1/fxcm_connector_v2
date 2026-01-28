from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from config.config import Config
from core.time.buckets import TF_TO_MS
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from observability.metrics import Metrics
from runtime.fxcm.history_budget import HistoryBudget
from runtime.history_provider import HistoryProvider
from runtime.publisher import RedisPublisher
from runtime.repair import RepairSummary, repair_missing_1m
from runtime.republish import republish_tail
from runtime.status import StatusManager
from store.file_cache import FileCache


@dataclass
class TailGuardTfState:
    missing_bars: int
    status: str
    skipped_by_ttl: bool
    missing_ranges: List[Tuple[int, int]]


@dataclass
class TailGuardSummary:
    tf_states: Dict[str, TailGuardTfState]
    repaired: bool
    repair_summary: Optional[RepairSummary] = None


@dataclass
class TailGuardMark:
    verified_from_ms: int
    verified_until_ms: int
    checked_until_close_ms: int
    etag_last_complete_bar_ms: int
    last_audit_ts_ms: int


def run_tail_guard(
    config: Config,
    file_cache: FileCache,
    calendar: Calendar,
    provider: Optional[HistoryProvider],
    redis_client: Optional[Any],
    publisher: RedisPublisher,
    validator: SchemaValidator,
    status: StatusManager,
    metrics: Optional[Metrics],
    symbol: str,
    window_hours: int,
    repair: bool,
    republish_after_repair: bool,
    republish_force: bool,
    tfs: Optional[List[str]] = None,
    tier: str = "far",
    history_budget: Optional[HistoryBudget] = None,
) -> TailGuardSummary:
    tf_states: Dict[str, TailGuardTfState] = {}
    repaired = False
    repair_summary: Optional[RepairSummary] = None
    tfs = list(tfs or config.tail_guard_allow_tfs)
    all_tfs = list(config.tail_guard_allow_tfs)
    _ = republish_force

    rows, _meta = file_cache.load(symbol, "1m")
    if not rows:
        status.append_error(
            code="ssot_empty",
            severity="error",
            message="SSOT cache 1m порожній; tail_guard неможливий",
            context={"symbol": symbol, "window_hours": window_hours},
        )
        for tf in all_tfs:
            state = TailGuardTfState(
                missing_bars=0,
                status="cache_empty" if tf == "1m" else "ssot_empty",
                skipped_by_ttl=False,
                missing_ranges=[],
            )
            tf_states[tf] = state
            status.record_tail_guard_tf(tf=tf, state=state, window_hours=window_hours, tier=tier)
        status.record_tail_guard_summary(
            window_hours=window_hours,
            tf_states=tf_states,
            repaired=False,
            tier=tier,
        )
        return TailGuardSummary(tf_states=tf_states, repaired=False)

    for tf in tfs:
        if tf != "1m":
            state = TailGuardTfState(missing_bars=0, status="unsupported", skipped_by_ttl=False, missing_ranges=[])
            tf_states[tf] = state
            status.record_tail_guard_tf(tf=tf, state=state, window_hours=window_hours, tier=tier)
            continue
        state = _audit_1m(
            config=config,
            file_cache=file_cache,
            calendar=calendar,
            metrics=metrics,
            symbol=symbol,
            window_hours=window_hours,
        )
        tf_states[tf] = state
        status.record_tail_guard_tf(tf=tf, state=state, window_hours=window_hours, tier=tier)

    if repair:
        now_ms = int(time.time() * 1000)
        if not calendar.is_repair_window(now_ms, config.tail_guard_safe_repair_only_when_market_closed):
            for tf in tf_states:
                state = tf_states[tf]
                tf_states[tf] = TailGuardTfState(
                    missing_bars=state.missing_bars,
                    status="deferred",
                    skipped_by_ttl=state.skipped_by_ttl,
                    missing_ranges=state.missing_ranges,
                )
                status.record_tail_guard_tf(tf=tf, state=tf_states[tf], window_hours=window_hours, tier=tier)
            status.mark_degraded("repair_deferred_market_open")
            status.record_tail_guard_summary(
                window_hours=window_hours,
                tf_states=tf_states,
                repaired=False,
                tier=tier,
            )
            return TailGuardSummary(tf_states=tf_states, repaired=False)

        missing_ranges = tf_states.get("1m", TailGuardTfState(0, "ok", False, [])).missing_ranges
        if missing_ranges:
            if provider is None:
                status.append_error(
                    code="repair_source_unavailable",
                    severity="error",
                    message="Джерело для repair недоступне",
                    context={"symbol": symbol},
                )
                status.mark_degraded("repair_source_unavailable")
            else:
                repair_summary = repair_missing_1m(
                    config=config,
                    file_cache=file_cache,
                    provider=provider,
                    status=status,
                    metrics=metrics,
                    symbol=symbol,
                    ranges=missing_ranges,
                    max_gap_minutes=config.tail_guard_repair_max_gap_minutes,
                    calendar=calendar,
                    history_budget=history_budget,
                )
                if repair_summary.windows_repaired > 0 and republish_after_repair:
                    republish_tail(
                        config=config,
                        file_cache=file_cache,
                        redis_client=redis_client,
                        publisher=publisher,
                        validator=validator,
                        status=status,
                        metrics=metrics,
                        symbol=symbol,
                        timeframes=["1m"],
                        window_hours=window_hours,
                        force=True,
                        req_id="tail_guard_repair",
                    )
                repaired = True

    status.record_tail_guard_summary(
        window_hours=window_hours,
        tf_states=tf_states,
        repaired=repaired,
        tier=tier,
    )
    return TailGuardSummary(tf_states=tf_states, repaired=repaired, repair_summary=repair_summary)


def _audit_1m(
    config: Config,
    file_cache: FileCache,
    calendar: Calendar,
    metrics: Optional[Metrics],
    symbol: str,
    window_hours: int,
) -> TailGuardTfState:
    rows = file_cache.query(symbol=symbol, tf="1m", limit=window_hours * 60)
    if not rows:
        return TailGuardTfState(missing_bars=0, status="cache_empty", skipped_by_ttl=False, missing_ranges=[])
    missing_ranges = _find_missing_ranges(rows, calendar, symbol)
    missing_bars = sum(int((end - start + 1) / 60_000) for start, end in missing_ranges)
    status = "ok" if missing_bars == 0 else "missing"
    if metrics is not None:
        metrics.tail_guard_runs_total.labels(tf="1m").inc()
        if missing_bars:
            metrics.tail_guard_missing_total.inc(missing_bars)
    return TailGuardTfState(
        missing_bars=missing_bars,
        status=status,
        skipped_by_ttl=False,
        missing_ranges=missing_ranges,
    )


def _find_missing_ranges(rows: List[Dict[str, Any]], calendar: Calendar, symbol: str) -> List[Tuple[int, int]]:
    rows_sorted = sorted(rows, key=lambda r: int(r["open_time_ms"]))
    missing_ranges: List[Tuple[int, int]] = []
    tf_ms = TF_TO_MS["1m"]
    prev_open = int(rows_sorted[0]["open_time_ms"])
    for row in rows_sorted[1:]:
        open_ms = int(row["open_time_ms"])
        expected = prev_open + tf_ms
        if open_ms > expected:
            t = expected
            range_start: Optional[int] = None
            while t < open_ms:
                if calendar.is_open(t, symbol=str(symbol)):
                    if range_start is None:
                        range_start = t
                else:
                    if range_start is not None:
                        missing_ranges.append((range_start, t - 1))
                        range_start = None
                t += tf_ms
            if range_start is not None:
                missing_ranges.append((range_start, open_ms - 1))
        prev_open = open_ms
    return missing_ranges
