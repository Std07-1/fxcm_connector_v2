from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from prometheus_client import CollectorRegistry, Counter, Gauge, start_http_server


@dataclass
class Metrics:
    """Контейнер метрик P0."""

    commands_total: Counter
    errors_total: Counter
    uptime_seconds: Gauge
    last_status_ts_ms: Gauge
    ticks_total: Counter
    tick_errors_total: Counter
    tick_contract_reject_total: Counter
    last_tick_ts_ms: Gauge
    tick_lag_ms: Gauge
    fxcm_ticks_total: Counter
    fxcm_ticks_dropped_total: Counter
    fxcm_last_tick_ts_ms: Gauge
    fxcm_tick_skew_ms: Gauge
    fxcm_stale_events_total: Counter
    fxcm_reconnect_total: Counter
    fxcm_resubscribe_total: Counter
    fxcm_publish_fail_total: Counter
    fxcm_contract_reject_total: Counter
    fxcm_history_inflight: Gauge
    fxcm_history_throttled_total: Counter
    fxcm_history_not_ready_total: Counter
    fxcm_history_backoff_active: Gauge
    ohlcv_preview_total: Counter
    ohlcv_preview_errors_total: Counter
    ohlcv_preview_batches_total: Counter
    ohlcv_preview_validation_errors_total: Counter
    ohlcv_preview_last_publish_ts_ms: Gauge
    ohlcv_final_validation_errors_total: Counter
    store_upserts_total: Counter
    warmup_requests_total: Counter
    backfill_requests_total: Counter
    tail_guard_audits_total: Counter
    tail_guard_missing_total: Counter
    tail_guard_runs_total: Counter
    tail_guard_repairs_total: Counter
    republish_runs_total: Counter
    republish_skipped_total: Counter
    republish_forced_total: Counter
    derived_rebuild_runs_total: Counter
    derived_rebuild_errors_total: Counter
    no_mix_conflicts_total: Counter
    htf_final_bars_upserted_total: Counter
    status_payload_too_large_total: Counter


def create_metrics(registry: Optional[CollectorRegistry] = None) -> Metrics:
    commands_total = Counter(
        "connector_commands_total",
        "Кількість оброблених команд",
        ["cmd", "state"],
        registry=registry,
    )
    errors_total = Counter(
        "connector_errors_total",
        "Кількість помилок",
        ["code", "severity"],
        registry=registry,
    )
    uptime_seconds = Gauge(
        "connector_uptime_seconds",
        "Uptime конектора у секундах",
        registry=registry,
    )
    last_status_ts_ms = Gauge(
        "connector_last_status_ts_ms",
        "Останній ts статусу у ms",
        registry=registry,
    )
    ticks_total = Counter(
        "connector_ticks_total",
        "Кількість tick",
        registry=registry,
    )
    tick_errors_total = Counter(
        "connector_tick_errors_total",
        "Кількість помилок tick",
        registry=registry,
    )
    tick_contract_reject_total = Counter(
        "connector_tick_contract_reject_total",
        "Кількість відхилених tick через контракт",
        registry=registry,
    )
    last_tick_ts_ms = Gauge(
        "connector_last_tick_ts_ms",
        "Останній tick_ts у ms",
        registry=registry,
    )
    tick_lag_ms = Gauge(
        "connector_tick_lag_ms",
        "Лаг tick у ms",
        registry=registry,
    )
    fxcm_ticks_total = Counter(
        "connector_fxcm_ticks_total",
        "Кількість FXCM tick",
        registry=registry,
    )
    fxcm_ticks_dropped_total = Counter(
        "connector_fxcm_ticks_dropped_total",
        "Кількість FXCM tick, які відкинуті",
        ["reason"],
        registry=registry,
    )
    fxcm_last_tick_ts_ms = Gauge(
        "connector_fxcm_last_tick_ts_ms",
        "Останній FXCM tick_ts у ms",
        registry=registry,
    )
    fxcm_tick_skew_ms = Gauge(
        "connector_fxcm_tick_skew_ms",
        "Різниця snap_ts_ms - tick_ts_ms для FXCM",
        registry=registry,
    )
    fxcm_stale_events_total = Counter(
        "connector_fxcm_stale_events_total",
        "Кількість stale подій FXCM",
        registry=registry,
    )
    fxcm_reconnect_total = Counter(
        "connector_fxcm_reconnect_total",
        "Кількість reconnect FXCM",
        registry=registry,
    )
    fxcm_resubscribe_total = Counter(
        "connector_fxcm_resubscribe_total",
        "Кількість resubscribe FXCM",
        registry=registry,
    )
    fxcm_publish_fail_total = Counter(
        "connector_fxcm_publish_fail_total",
        "Кількість помилок publish FXCM",
        registry=registry,
    )
    fxcm_contract_reject_total = Counter(
        "connector_fxcm_contract_reject_total",
        "Кількість contract reject FXCM",
        registry=registry,
    )
    fxcm_history_inflight = Gauge(
        "connector_fxcm_history_inflight",
        "Кількість inflight history запитів FXCM",
        registry=registry,
    )
    fxcm_history_throttled_total = Counter(
        "connector_fxcm_history_throttled_total",
        "Кількість випадків очікування history budget",
        registry=registry,
    )
    fxcm_history_not_ready_total = Counter(
        "connector_fxcm_history_not_ready_total",
        "Кількість випадків history not ready",
        ["reason"],
        registry=registry,
    )
    fxcm_history_backoff_active = Gauge(
        "connector_fxcm_history_backoff_active",
        "Чи активний history backoff",
        registry=registry,
    )
    ohlcv_preview_total = Counter(
        "connector_ohlcv_preview_total",
        "Кількість preview OHLCV batch",
        registry=registry,
    )
    ohlcv_preview_errors_total = Counter(
        "connector_ohlcv_preview_errors_total",
        "Кількість помилок preview OHLCV",
        registry=registry,
    )
    ohlcv_preview_batches_total = Counter(
        "connector_ohlcv_preview_batches_total",
        "Кількість preview batch OHLCV",
        registry=registry,
    )
    ohlcv_preview_validation_errors_total = Counter(
        "connector_ohlcv_preview_validation_errors_total",
        "Кількість помилок валідації preview OHLCV",
        registry=registry,
    )
    ohlcv_preview_last_publish_ts_ms = Gauge(
        "connector_ohlcv_preview_last_publish_ts_ms",
        "Останній час публікації preview OHLCV",
        registry=registry,
    )
    ohlcv_final_validation_errors_total = Counter(
        "connector_ohlcv_final_validation_errors_total",
        "Кількість помилок валідації final OHLCV",
        registry=registry,
    )
    store_upserts_total = Counter(
        "connector_store_upserts_total",
        "Кількість upsert у SQLite store",
        registry=registry,
    )
    warmup_requests_total = Counter(
        "connector_warmup_requests_total",
        "Кількість history запитів warmup",
        registry=registry,
    )
    backfill_requests_total = Counter(
        "connector_backfill_requests_total",
        "Кількість history запитів backfill",
        registry=registry,
    )
    tail_guard_audits_total = Counter(
        "connector_tail_guard_audits_total",
        "Кількість audit tail_guard",
        registry=registry,
    )
    tail_guard_missing_total = Counter(
        "connector_tail_guard_missing_total",
        "Кількість missing bar у tail_guard",
        registry=registry,
    )
    tail_guard_runs_total = Counter(
        "connector_tail_guard_runs_total",
        "Кількість запусків tail_guard",
        ["tf"],
        registry=registry,
    )
    tail_guard_repairs_total = Counter(
        "connector_tail_guard_repairs_total",
        "Кількість repair у tail_guard",
        ["tf"],
        registry=registry,
    )
    republish_runs_total = Counter(
        "connector_republish_runs_total",
        "Кількість запусків republish",
        ["tf"],
        registry=registry,
    )
    republish_skipped_total = Counter(
        "connector_republish_skipped_total",
        "Кількість пропусків republish через watermark",
        ["tf"],
        registry=registry,
    )
    republish_forced_total = Counter(
        "connector_republish_forced_total",
        "Кількість force republish",
        ["tf"],
        registry=registry,
    )
    derived_rebuild_runs_total = Counter(
        "connector_derived_rebuild_runs_total",
        "Кількість запусків rebuild derived",
        ["tf"],
        registry=registry,
    )
    derived_rebuild_errors_total = Counter(
        "connector_derived_rebuild_errors_total",
        "Кількість помилок rebuild derived",
        ["tf", "code"],
        registry=registry,
    )
    no_mix_conflicts_total = Counter(
        "connector_no_mix_conflicts_total",
        "Кількість NoMix конфліктів",
        ["tf"],
        registry=registry,
    )
    htf_final_bars_upserted_total = Counter(
        "connector_htf_final_bars_upserted_total",
        "Кількість upsert HTF final барів",
        ["tf"],
        registry=registry,
    )
    status_payload_too_large_total = Counter(
        "connector_status_payload_too_large_total",
        "Кількість перевищень ліміту статус payload (pubsub)",
        registry=registry,
    )
    return Metrics(
        commands_total=commands_total,
        errors_total=errors_total,
        uptime_seconds=uptime_seconds,
        last_status_ts_ms=last_status_ts_ms,
        ticks_total=ticks_total,
        tick_errors_total=tick_errors_total,
        tick_contract_reject_total=tick_contract_reject_total,
        last_tick_ts_ms=last_tick_ts_ms,
        tick_lag_ms=tick_lag_ms,
        fxcm_ticks_total=fxcm_ticks_total,
        fxcm_ticks_dropped_total=fxcm_ticks_dropped_total,
        fxcm_last_tick_ts_ms=fxcm_last_tick_ts_ms,
        fxcm_tick_skew_ms=fxcm_tick_skew_ms,
        fxcm_stale_events_total=fxcm_stale_events_total,
        fxcm_reconnect_total=fxcm_reconnect_total,
        fxcm_resubscribe_total=fxcm_resubscribe_total,
        fxcm_publish_fail_total=fxcm_publish_fail_total,
        fxcm_contract_reject_total=fxcm_contract_reject_total,
        fxcm_history_inflight=fxcm_history_inflight,
        fxcm_history_throttled_total=fxcm_history_throttled_total,
        fxcm_history_not_ready_total=fxcm_history_not_ready_total,
        fxcm_history_backoff_active=fxcm_history_backoff_active,
        ohlcv_preview_total=ohlcv_preview_total,
        ohlcv_preview_errors_total=ohlcv_preview_errors_total,
        ohlcv_preview_batches_total=ohlcv_preview_batches_total,
        ohlcv_preview_validation_errors_total=ohlcv_preview_validation_errors_total,
        ohlcv_preview_last_publish_ts_ms=ohlcv_preview_last_publish_ts_ms,
        ohlcv_final_validation_errors_total=ohlcv_final_validation_errors_total,
        store_upserts_total=store_upserts_total,
        warmup_requests_total=warmup_requests_total,
        backfill_requests_total=backfill_requests_total,
        tail_guard_audits_total=tail_guard_audits_total,
        tail_guard_missing_total=tail_guard_missing_total,
        tail_guard_runs_total=tail_guard_runs_total,
        tail_guard_repairs_total=tail_guard_repairs_total,
        republish_runs_total=republish_runs_total,
        republish_skipped_total=republish_skipped_total,
        republish_forced_total=republish_forced_total,
        derived_rebuild_runs_total=derived_rebuild_runs_total,
        derived_rebuild_errors_total=derived_rebuild_errors_total,
        no_mix_conflicts_total=no_mix_conflicts_total,
        htf_final_bars_upserted_total=htf_final_bars_upserted_total,
        status_payload_too_large_total=status_payload_too_large_total,
    )


def start_metrics_server(port: int) -> None:
    """Запускає /metrics сервер."""
    start_http_server(port)
