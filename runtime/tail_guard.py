from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from config.config import Config
from core.time.buckets import TF_TO_MS, floor_to_bucket_ms
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from observability.metrics import Metrics
from runtime.fxcm.history_budget import HistoryBudget
from runtime.history_provider import HistoryProvider
from runtime.publisher import RedisPublisher
from runtime.rebuild_derived import DerivedRebuildCoordinator
from runtime.repair import RepairSummary, repair_missing_1m
from runtime.republish import republish_tail
from runtime.status import StatusManager
from store.sqlite_store import SQLiteStore


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
    store: SQLiteStore,
    calendar: Calendar,
    provider: Optional[HistoryProvider],
    redis_client: Optional[Any],
    derived_rebuilder: DerivedRebuildCoordinator,
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

    now_ms = int(time.time() * 1000)
    total_1m = store.count_1m_final(symbol)
    if total_1m <= 0:
        status.append_error(
            code="ssot_empty",
            severity="error",
            message="SSOT 1m final порожній; tail_guard неможливий",
            context={"symbol": symbol, "window_hours": window_hours},
        )
        status.record_tail_guard_summary(
            window_hours=window_hours,
            tf_states={
                tf: TailGuardTfState(
                    missing_bars=0,
                    status="store_empty" if tf == "1m" else "ssot_empty",
                    skipped_by_ttl=False,
                    missing_ranges=[],
                )
                for tf in all_tfs
            },
            repaired=False,
            tier=tier,
        )
        for tf in all_tfs:
            state = TailGuardTfState(
                missing_bars=0,
                status="store_empty" if tf == "1m" else "ssot_empty",
                skipped_by_ttl=False,
                missing_ranges=[],
            )
            tf_states[tf] = state
            status.record_tail_guard_tf(tf=tf, state=state, window_hours=window_hours)
        raise ValueError("SSOT 1m final порожній; tail_guard неможливий")

    for tf in tfs:
        state, mark = _audit_tf(
            config=config,
            store=store,
            calendar=calendar,
            redis_client=redis_client,
            metrics=metrics,
            symbol=symbol,
            tf=tf,
            window_hours=window_hours,
            tier=tier,
            persist_verified=(tier != "near"),
        )
        tf_states[tf] = state
        status.record_tail_guard_tf(tf=tf, state=state, window_hours=window_hours, tier=tier)
        if mark is not None:
            status.record_tail_guard_mark(
                tf=tf,
                mark={
                    "verified_from_ms": mark.verified_from_ms,
                    "verified_until_ms": mark.verified_until_ms,
                    "checked_until_close_ms": mark.checked_until_close_ms,
                    "etag_last_complete_bar_ms": mark.etag_last_complete_bar_ms,
                    "last_audit_ts_ms": mark.last_audit_ts_ms,
                },
                tier=tier,
            )

    if repair:
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

        missing_any = any(s.missing_bars > 0 for s in tf_states.values())
        if missing_any:
            if provider is None:
                status.append_error(
                    code="repair_source_unavailable",
                    severity="error",
                    message="Джерело для repair недоступне",
                    context={"symbol": symbol},
                )
                status.mark_degraded("repair_source_unavailable")
            else:
                missing_ranges = tf_states.get("1m", TailGuardTfState(0, "ok", False, [])).missing_ranges
                repair_summary = repair_missing_1m(
                    config=config,
                    store=store,
                    provider=provider,
                    status=status,
                    metrics=metrics,
                    symbol=symbol,
                    ranges=missing_ranges,
                    max_gap_minutes=config.tail_guard_repair_max_gap_minutes,
                    calendar=calendar,
                    history_budget=history_budget,
                )
                if repair_summary.windows_repaired > 0 and missing_ranges:
                    start_ms = min(r[0] for r in missing_ranges)
                    end_ms = max(r[1] for r in missing_ranges)
                    derived_rebuilder.rebuild(
                        config=config,
                        store=store,
                        status=status,
                        metrics=metrics,
                        publisher=publisher,
                        validator=validator,
                        symbol=symbol,
                        tfs=["15m", "1h", "4h", "1d"],
                        start_ms=start_ms,
                        end_ms=end_ms,
                    )
                    if republish_after_repair:
                        republish_tail(
                            config=config,
                            store=store,
                            redis_client=redis_client,
                            publisher=publisher,
                            validator=validator,
                            status=status,
                            metrics=metrics,
                            symbol=symbol,
                            timeframes=["1m", "15m", "1h", "4h", "1d"],
                            window_hours=window_hours,
                            force=True,
                            req_id="tail_guard_repair",
                        )
                repaired = True
                if metrics is not None:
                    for tf, state in tf_states.items():
                        if state.missing_bars > 0:
                            metrics.tail_guard_repairs_total.labels(tf=tf).inc()

    status.record_tail_guard_summary(
        window_hours=window_hours,
        tf_states=tf_states,
        repaired=repaired,
        tier=tier,
    )
    return TailGuardSummary(tf_states=tf_states, repaired=repaired, repair_summary=repair_summary)


def _audit_tf(
    config: Config,
    store: SQLiteStore,
    calendar: Calendar,
    redis_client: Optional[Any],
    metrics: Optional[Metrics],
    symbol: str,
    tf: str,
    window_hours: int,
    tier: str,
    persist_verified: bool,
) -> Tuple[TailGuardTfState, Optional[TailGuardMark]]:
    _ = redis_client
    real_now_ms = int(time.time() * 1000)
    ttl_s = int(config.tail_guard_checked_ttl_s)

    if tf == "1m":
        last_close = store.get_last_complete_close_ms(symbol)
        if last_close > 0:
            end_open_ms = int(last_close - 60_000 + 1)
        else:
            end_open_ms = real_now_ms - (real_now_ms % 60_000) - 60_000
        end_ms = end_open_ms + 60_000 - 1
        last_complete_bar_ms = int(last_close) if last_close > 0 else 0
    else:
        size = TF_TO_MS[tf]
        tail = store.query_htf_tail(symbol, tf, limit=1)
        if tail:
            end_open_ms = int(tail[-1]["open_time_ms"])
            last_complete_bar_ms = int(tail[-1]["close_time_ms"])
        else:
            end_open_ms = floor_to_bucket_ms(real_now_ms, tf)
            last_complete_bar_ms = 0
        end_ms = end_open_ms + size - 1

    mark_state = store.get_tail_audit_state(symbol, tf)
    if tier == "near":
        should_skip = _should_skip_by_mark_near(mark_state, last_complete_bar_ms, end_ms, real_now_ms, ttl_s)
    else:
        should_skip = _should_skip_by_mark_far(mark_state, last_complete_bar_ms, end_ms, real_now_ms, ttl_s)
    if should_skip:
        if mark_state is None:
            raise ValueError("Неможливо пропустити audit без збереженого mark_state.")
        skip_mark = TailGuardMark(
            verified_from_ms=int(mark_state.get("verified_from_ms", 0)),
            verified_until_ms=int(mark_state.get("verified_until_ms", 0)),
            checked_until_close_ms=int(mark_state.get("checked_until_close_ms", 0)),
            etag_last_complete_bar_ms=int(mark_state.get("etag_last_complete_bar_ms", 0)),
            last_audit_ts_ms=int(mark_state.get("last_audit_ts_ms", 0)),
        )
        return TailGuardTfState(missing_bars=0, status="ok", skipped_by_ttl=True, missing_ranges=[]), skip_mark

    if not calendar.is_open(end_ms, symbol=symbol):
        closed_mark = _persist_mark_if_ok(
            store=store,
            symbol=symbol,
            tf=tf,
            start_ms=end_open_ms,
            end_ms=end_ms,
            last_complete_bar_ms=last_complete_bar_ms,
            now_ms=real_now_ms,
            persist_verified=persist_verified,
        )
        return TailGuardTfState(missing_bars=0, status="closed", skipped_by_ttl=False, missing_ranges=[]), closed_mark

    if tf == "1m":
        start_open_ms = end_open_ms - (window_hours * 60 - 1) * 60_000
        bars = store.query_1m_range(symbol, start_open_ms, end_ms, limit=window_hours * 60 + 10)
        have = {int(b["open_time_ms"]) for b in bars}
        missing = 0
        missing_ranges: List[Tuple[int, int]] = []
        range_start: Optional[int] = None
        t = start_open_ms
        while t <= end_open_ms:
            if calendar.is_open(t, symbol=symbol) and t not in have:
                missing += 1
                if range_start is None:
                    range_start = t
            else:
                if range_start is not None:
                    missing_ranges.append((range_start, t - 60_000 + 59_999))
                    range_start = None
            t += 60_000
        if range_start is not None:
            missing_ranges.append((range_start, end_open_ms + 59_999))
    else:
        size = TF_TO_MS[tf]
        start_open_ms = end_open_ms - (window_hours * 60 * 60 * 1000) + size
        start_open_ms = floor_to_bucket_ms(start_open_ms, tf)
        rows = store.query_htf_range(
            symbol, tf, start_open_ms, end_open_ms, limit=int(window_hours * 60 * 60 * 1000 / size) + 10
        )
        have = {int(b["open_time_ms"]) for b in rows}
        missing = 0
        t = start_open_ms
        while t <= end_open_ms:
            if calendar.is_open(t, symbol=symbol) and t not in have:
                missing += 1
            t += size
        missing_ranges = []

    status = "ok" if missing == 0 else "missing"
    mark: Optional[TailGuardMark] = None
    if missing == 0 and status in {"ok", "closed"}:
        mark = _persist_mark_if_ok(
            store=store,
            symbol=symbol,
            tf=tf,
            start_ms=start_open_ms,
            end_ms=end_ms,
            last_complete_bar_ms=last_complete_bar_ms,
            now_ms=real_now_ms,
            persist_verified=persist_verified,
        )
    if metrics is not None:
        metrics.tail_guard_runs_total.labels(tf=tf).inc()
        if missing:
            metrics.tail_guard_missing_total.inc(missing)
            if status == "missing":
                metrics.tail_guard_repairs_total.labels(tf=tf).inc(0)
    return (
        TailGuardTfState(
            missing_bars=missing,
            status=status,
            skipped_by_ttl=False,
            missing_ranges=missing_ranges,
        ),
        mark,
    )


def _should_skip_by_mark_far(
    mark_state: Optional[Dict[str, Any]],
    last_complete_bar_ms: int,
    audit_to_ms: int,
    now_ms: int,
    ttl_s: int,
) -> bool:
    if not mark_state:
        return False
    verified_until = int(mark_state.get("verified_until_ms", 0))
    etag = int(mark_state.get("etag_last_complete_bar_ms", 0))
    last_audit = int(mark_state.get("last_audit_ts_ms", 0))
    if verified_until < audit_to_ms:
        return False
    if last_complete_bar_ms <= 0 or etag != last_complete_bar_ms:
        return False
    if ttl_s > 0 and now_ms - last_audit > ttl_s * 1000:
        return False
    return True


def _should_skip_by_mark_near(
    mark_state: Optional[Dict[str, Any]],
    last_complete_bar_ms: int,
    audit_to_ms: int,
    now_ms: int,
    ttl_s: int,
) -> bool:
    if not mark_state:
        return False
    checked_until = int(mark_state.get("checked_until_close_ms", 0))
    etag = int(mark_state.get("etag_last_complete_bar_ms", 0))
    last_audit = int(mark_state.get("last_audit_ts_ms", 0))
    if checked_until < audit_to_ms:
        return False
    if last_complete_bar_ms <= 0 or etag != last_complete_bar_ms:
        return False
    if ttl_s > 0 and now_ms - last_audit > ttl_s * 1000:
        return False
    return True


def _persist_mark_if_ok(
    store: SQLiteStore,
    symbol: str,
    tf: str,
    start_ms: int,
    end_ms: int,
    last_complete_bar_ms: int,
    now_ms: int,
    persist_verified: bool,
) -> TailGuardMark:
    verified_from = int(start_ms)
    verified_until = int(end_ms)
    if not persist_verified:
        existing = store.get_tail_audit_state(symbol, tf)
        if existing:
            verified_from = int(existing.get("verified_from_ms", 0))
            verified_until = int(existing.get("verified_until_ms", 0))
            if verified_from <= 0 or verified_until <= 0:
                verified_from = int(start_ms)
                verified_until = int(end_ms)
    mark = TailGuardMark(
        verified_from_ms=int(verified_from),
        verified_until_ms=int(verified_until),
        checked_until_close_ms=int(end_ms),
        etag_last_complete_bar_ms=int(last_complete_bar_ms),
        last_audit_ts_ms=int(now_ms),
    )
    store.upsert_tail_audit_state(
        {
            "symbol": symbol,
            "tf": tf,
            "verified_from_ms": mark.verified_from_ms,
            "verified_until_ms": mark.verified_until_ms,
            "checked_until_close_ms": mark.checked_until_close_ms,
            "etag_last_complete_bar_ms": mark.etag_last_complete_bar_ms,
            "last_audit_ts_ms": mark.last_audit_ts_ms,
            "updated_ts_ms": mark.last_audit_ts_ms,
        }
    )
    return mark
