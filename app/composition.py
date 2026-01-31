from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import redis

from config.config import Config
from core.runtime.mode import BackendMode
from core.time.buckets import TF_TO_MS, get_bucket_open_ms
from core.time.calendar import Calendar
from core.time.sessions import _to_utc_iso
from core.validation.validator import ContractError, SchemaValidator
from observability.metrics import Metrics, create_metrics, start_metrics_server
from runtime.command_bus import CommandBus
from runtime.fxcm.history_budget import build_history_budget
from runtime.fxcm.history_provider import FxcmForexConnectHistoryAdapter, FxcmHistoryProvider
from runtime.fxcm_forexconnect import FxcmForexConnectHandle, FxcmForexConnectStream
from runtime.handlers_p3 import handle_backfill_command, handle_warmup_command
from runtime.history_provider import HistoryProvider, ProviderNotConfiguredError
from runtime.http_server import HttpServer
from runtime.no_mix import NoMixDetector
from runtime.ohlcv_preview import PreviewCandleBuilder, select_closed_bars_for_archive
from runtime.preview_builder import OhlcvCache
from runtime.publisher import RedisPublisher
from runtime.replay_ticks import ReplayTickHandle, ReplayTickStream
from runtime.republish import republish_tail
from runtime.status import StatusManager
from runtime.tail_guard import run_tail_guard
from runtime.tick_feed import TickPublisher
from store.file_cache import FileCache
from ui_lite.server import UiLiteHandle, start_ui_lite

log = logging.getLogger("fxcm_p0")


@dataclass
class RuntimeHandles:
    config: Config
    status: StatusManager
    command_bus: CommandBus
    http_server: HttpServer
    ui_lite_handle: Optional[UiLiteHandle]
    fxcm_handle: Optional[FxcmForexConnectHandle]
    replay_handle: Optional[ReplayTickHandle]
    mode: BackendMode


def _resolve_mode(config: Config) -> BackendMode:
    if config.fxcm_backend == "forexconnect":
        return BackendMode.FOREXCONNECT
    if config.fxcm_backend == "replay":
        return BackendMode.REPLAY
    if config.fxcm_backend == "disabled":
        return BackendMode.DISABLED
    if config.fxcm_backend == "sim":
        return BackendMode.SIM
    raise SystemExit(f"Невідомий fxcm_backend: {config.fxcm_backend}")


def _ensure_no_sim(config: Config) -> None:
    if config.tick_mode not in {"off", "fxcm"} or config.preview_mode != "off" or config.ohlcv_sim_enabled:
        raise SystemExit("Runtime sim-режими видалені: вимкніть tick/preview/ohlcv sim")


def _ensure_tick_mode(config: Config) -> None:
    if config.tick_mode == "fxcm" and config.fxcm_backend != "forexconnect":
        raise SystemExit("tick_mode=fxcm потребує fxcm_backend=forexconnect")


def build_history_provider_for_runtime(
    config: Config,
    status: StatusManager,
    metrics: Optional[Metrics],
) -> Optional[HistoryProvider]:
    if config.history_provider_kind == "fxcm_forexconnect":
        history_budget = build_history_budget(int(config.max_requests_per_minute))
        return FxcmHistoryProvider(
            adapter=FxcmForexConnectHistoryAdapter(config=config),
            budget=history_budget,
            status=status,
            metrics=metrics,
            chunk_minutes=int(config.history_chunk_minutes),
            min_sleep_ms=int(config.history_min_sleep_ms),
        )
    if config.history_provider_kind == "none":
        return None
    raise SystemExit(f"Невідомий history_provider_kind: {config.history_provider_kind}")


def build_runtime(config: Config, fxcm_preview: bool) -> RuntimeHandles:
    mode = _resolve_mode(config)
    _ensure_no_sim(config)
    _ensure_tick_mode(config)

    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)

    file_cache: Optional[FileCache] = None
    if config.cache_enabled:
        file_cache = FileCache(
            root=Path(config.cache_root),
            max_bars=int(config.cache_max_bars),
            warmup_bars=int(config.cache_warmup_bars),
            strict=bool(config.cache_strict),
        )

    redis_client = redis.Redis.from_url(config.redis_dsn(), decode_responses=True)
    no_mix = NoMixDetector()
    publisher = RedisPublisher(redis_client, config, no_mix=no_mix, status=None)

    metrics = None
    if config.metrics_enabled:
        metrics = create_metrics()
        start_metrics_server(config.metrics_port)
        log.info("/metrics піднято на порту %s", config.metrics_port)

    calendar = Calendar(
        calendar_tag=config.calendar_tag,
        overrides_path=config.calendar_path,
    )
    validator.calendar = calendar

    status = StatusManager(
        config=config,
        validator=validator,
        publisher=publisher,
        calendar=calendar,
        metrics=metrics,
    )
    status.build_initial_snapshot()
    publisher.set_status(status)

    if not config.cache_enabled:
        status.mark_degraded("cache_disabled")
        status.append_error(
            code="cache_disabled",
            severity="warn",
            message="File cache вимкнений у конфігу",
        )

    history_provider = build_history_provider_for_runtime(config=config, status=status, metrics=metrics)

    if mode == BackendMode.SIM:
        status.append_error(
            code="sim_forbidden",
            severity="error",
            message="SIM режим заборонений у runtime",
        )
        status.publish_snapshot()
        raise ContractError("SIM режим заборонений у runtime")

    if fxcm_preview:
        if not config.fxcm_username or not config.fxcm_password:
            status.append_error(
                code="fxcm_secrets_missing",
                severity="error",
                message="FXCM secrets відсутні у .env.local/.env.prod",
            )
            status.mark_degraded("fxcm_secrets_missing")
            status.update_fxcm_state(
                state="error",
                last_tick_ts_ms=0,
                last_err="fxcm_secrets_missing",
                last_err_ts_ms=int(time.time() * 1000),
                reconnect_attempt=0,
                next_retry_ts_ms=0,
            )
            status.publish_snapshot()
            raise SystemExit("FXCM preview: secrets відсутні")

    cache = OhlcvCache()
    preview_builder = PreviewCandleBuilder(config=config, cache=cache, calendar=calendar, status=status)

    http_server = HttpServer(
        config=config,
        redis_client=redis_client,
        cache=cache,
        file_cache=file_cache,
    )
    http_server.start()
    log.info("HTTP chart піднято на порту %s", config.http_port)

    def _select_provider(name: str) -> HistoryProvider:
        if name == "sim":
            raise ProviderNotConfiguredError(
                "SIM провайдер видалений: використайте tools/record_*/replay_* або інший провайдер"
            )
        provider_name = str(name or "").strip().lower()
        if provider_name in {"", "default"}:
            provider_name = str(config.history_provider_kind).strip().lower()
        if provider_name in {"none", "disabled"}:
            raise ProviderNotConfiguredError("History provider не налаштований")
        if provider_name in {"fxcm_forexconnect", "fxcm"}:
            if history_provider is None:
                raise ProviderNotConfiguredError("FXCM history provider не налаштований")
            return history_provider
        raise ValueError("Невідомий provider для історії")

    def _publish_final_tail(symbol: str, window_hours: int) -> None:
        if file_cache is None:
            return
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - window_hours * 60 * 60 * 1000
        bars = file_cache.query(
            symbol=symbol,
            tf="1m",
            limit=config.max_bars_per_message,
            since_open_ms=start_ms,
            until_open_ms=end_ms,
        )
        if not bars:
            return
        payload_bars = []
        for b in bars:
            payload_bars.append(
                {
                    "open_time": int(b["open_time_ms"]),
                    "close_time": int(b["close_time_ms"]),
                    "open": float(b["open"]),
                    "high": float(b["high"]),
                    "low": float(b["low"]),
                    "close": float(b["close"]),
                    "volume": float(b["volume"]),
                    "complete": True,
                    "synthetic": False,
                    "source": "history",
                    "event_ts": int(b["close_time_ms"]),
                }
            )
        try:
            publisher.publish_ohlcv_final_1m(
                symbol=symbol,
                bars=payload_bars,
                validator=validator,
            )
        except ContractError as exc:
            status.append_error(
                code="final_ohlcv_contract_error",
                severity="error",
                message=str(exc),
                context={"symbol": symbol},
            )
            if metrics is not None:
                metrics.ohlcv_final_validation_errors_total.inc()
        status.publish_snapshot()

    def _handle_warmup(payload: dict) -> None:
        args = payload.get("args", {})
        provider_name = str(args.get("provider", ""))
        provider = _select_provider(provider_name)
        if file_cache is None:
            raise ValueError("cache вимкнений: warmup неможливий")
        handle_warmup_command(
            payload=payload,
            config=config,
            file_cache=file_cache,
            provider=provider,
            status=status,
            metrics=metrics,
            publish_tail=_publish_final_tail,
            rebuild_callback=None,
        )

    def _handle_backfill(payload: dict) -> None:
        args = payload.get("args", {})
        provider_name = str(args.get("provider", ""))
        provider = _select_provider(provider_name)
        if file_cache is None:
            raise ValueError("cache вимкнений: backfill неможливий")
        handle_backfill_command(
            payload=payload,
            config=config,
            file_cache=file_cache,
            provider=provider,
            status=status,
            metrics=metrics,
            publish_tail=_publish_final_tail,
            rebuild_callback=None,
        )

    def _handle_tail_guard(payload: dict) -> None:
        if file_cache is None:
            raise ValueError("cache вимкнений: tail_guard неможливий")
        args = payload.get("args", {})
        symbols = args.get("symbols", ["XAUUSD"])
        if isinstance(symbols, str):
            symbols = [symbols]
        if not isinstance(symbols, list) or not symbols:
            raise ValueError("symbols має бути list[str] або str")
        window_hours = int(args.get("window_hours", config.tail_guard_default_window_hours))
        repair = bool(args.get("repair", False))
        republish_after_repair = bool(args.get("republish_after_repair", True))
        republish_force = bool(args.get("republish_force", False))
        tfs = args.get("tfs")
        if tfs is None:
            tfs = config.tail_guard_allow_tfs
        if isinstance(tfs, str):
            tfs = [tfs]
        if not isinstance(tfs, list) or not tfs:
            raise ValueError("tfs має бути list[str]")
        provider_name = str(args.get("provider", ""))
        for symbol in symbols:
            started_ms = int(time.time() * 1000)
            summary = {
                "windows_repaired": 0,
                "bars_ingested": 0,
                "rebuild_tfs": [],
                "republish_window_hours": 0,
                "duration_ms": 0,
                "result": "ok",
            }
            near_window_hours = int(config.tail_guard_window_hours)
            if near_window_hours > 0 and near_window_hours != window_hours:
                run_tail_guard(
                    config=config,
                    file_cache=file_cache,
                    calendar=calendar,
                    provider=None,
                    redis_client=redis_client,
                    publisher=publisher,
                    validator=validator,
                    status=status,
                    metrics=metrics,
                    symbol=symbol,
                    window_hours=near_window_hours,
                    repair=False,
                    republish_after_repair=False,
                    republish_force=False,
                    tfs=[str(tf) for tf in tfs],
                    tier="near",
                )
            provider = _select_provider(provider_name)
            try:
                result = run_tail_guard(
                    config=config,
                    file_cache=file_cache,
                    calendar=calendar,
                    provider=provider,
                    redis_client=redis_client,
                    publisher=publisher,
                    validator=validator,
                    status=status,
                    metrics=metrics,
                    symbol=symbol,
                    window_hours=window_hours,
                    repair=repair,
                    republish_after_repair=republish_after_repair,
                    republish_force=republish_force,
                    tfs=[str(tf) for tf in tfs],
                    tier="far",
                )
                if repair and result.repair_summary is not None:
                    summary["windows_repaired"] = int(result.repair_summary.windows_repaired)
                    summary["bars_ingested"] = int(result.repair_summary.bars_ingested)
                    if result.repair_summary.windows_repaired > 0:
                        summary["rebuild_tfs"] = ["15m", "1h", "4h", "1d"]
                        if republish_after_repair:
                            summary["republish_window_hours"] = int(window_hours)
            except Exception:
                summary["result"] = "error"
                raise
            finally:
                summary["duration_ms"] = int(time.time() * 1000) - started_ms
                status.update_last_command_result(summary)
            status.publish_snapshot()

    def _handle_republish_tail(payload: dict) -> None:
        if file_cache is None:
            raise ValueError("cache вимкнений: republish неможливий")
        args = payload.get("args", {})
        symbol = str(args.get("symbol", ""))
        if not symbol:
            raise ValueError("symbol є обов'язковим")
        timeframes = args.get("timeframes", [])
        if not isinstance(timeframes, list) or not timeframes:
            raise ValueError("timeframes має бути list[str]")
        window_hours = int(args.get("window_hours", config.republish_tail_window_hours_default))
        force = bool(args.get("force", False))
        republish_tail(
            config=config,
            file_cache=file_cache,
            redis_client=redis_client,
            publisher=publisher,
            validator=validator,
            status=status,
            metrics=metrics,
            symbol=symbol,
            timeframes=timeframes,
            window_hours=window_hours,
            force=force,
            req_id=str(payload.get("req_id", "")),
        )
        status.publish_snapshot()

    handlers = {
        "fxcm_warmup": _handle_warmup,
        "fxcm_backfill": _handle_backfill,
        "fxcm_tail_guard": _handle_tail_guard,
        "fxcm_republish_tail": _handle_republish_tail,
    }
    command_bus = CommandBus(
        redis_client=redis_client,
        config=config,
        validator=validator,
        status=status,
        metrics=metrics,
        allowlist=set(handlers.keys()),
        handlers=handlers,
    )

    if config.commands_enabled:
        started = command_bus.start()
        if not started:
            status.append_error(
                code="command_bus_error",
                severity="error",
                message="Не вдалося запустити command_bus",
            )
            status.update_command_bus_error(
                channel=config.ch_commands(),
                code="command_bus_error",
                message="Не вдалося запустити command_bus",
            )
            status.publish_snapshot()
    status.publish_snapshot()

    tick_publisher = TickPublisher(
        config=config,
        publisher=publisher,
        validator=validator,
        status=status,
        metrics=metrics,
    )

    last_ohlcv_log_by_tf: dict = {}
    last_ohlcv_summary_log_ms = 0
    last_ohlcv_summary_info_ms = 0
    first_ok_summary_logged = False
    ohlcv_publish_counts_by_tf: dict = {}
    ohlcv_last_open_by_tf: dict = {}
    ohlcv_last_complete_by_tf: dict = {}
    ohlcv_prev_open_by_tf: dict = {}
    last_preview_rails = (0, 0, 0)
    last_archived_open_by_tf: dict = {}

    def _handle_fxcm_tick(
        symbol: str,
        bid: float,
        ask: float,
        mid: float,
        tick_ts_ms: int,
        snap_ts_ms: int,
    ) -> None:
        nonlocal last_ohlcv_summary_log_ms, last_ohlcv_summary_info_ms, last_preview_rails, first_ok_summary_logged
        if config.tick_mode == "fxcm":
            try:
                tick_publisher.publish_tick(
                    symbol=symbol,
                    bid=bid,
                    ask=ask,
                    mid=mid,
                    tick_ts_ms=tick_ts_ms,
                    snap_ts_ms=snap_ts_ms,
                )
            except ContractError:
                return
        if status.is_preview_paused():
            status.publish_snapshot()
            return
        preview_builder.on_tick(symbol=symbol, mid=mid, tick_ts_ms=tick_ts_ms)
        now_ms = int(time.time() * 1000)
        if preview_builder.should_publish(now_ms):
            payloads = preview_builder.build_payloads(symbol=symbol, limit=config.max_bars_per_message)
            for payload in payloads:
                bars = payload.get("bars", [])
                if not bars:
                    continue
                try:
                    publisher.publish_ohlcv_batch(
                        symbol=str(payload.get("symbol")),
                        tf=str(payload.get("tf")),
                        bars=bars,
                        source=str(payload.get("source", "stream")),
                        validator=validator,
                    )
                    tf_name = str(payload.get("tf"))
                    last_archived = int(last_archived_open_by_tf.get(tf_name, 0))
                    closed_bars = select_closed_bars_for_archive(bars, last_archived)
                    if closed_bars:
                        last_archived_open_by_tf[tf_name] = int(closed_bars[-1].get("open_time", last_archived))
                    if tf_name == "1m" and closed_bars:
                        if file_cache is None:
                            status.append_error(
                                code="cache_disabled",
                                severity="warn",
                                message="File cache вимкнений у конфігу",
                            )
                            status.mark_degraded("cache_disabled")
                        else:
                            try:
                                cache_bars = []
                                for bar in closed_bars:
                                    cache_bars.append(
                                        {
                                            "open_time": bar.get("open_time"),
                                            "close_time": bar.get("close_time"),
                                            "open": bar.get("open"),
                                            "high": bar.get("high"),
                                            "low": bar.get("low"),
                                            "close": bar.get("close"),
                                            "volume": bar.get("volume"),
                                            "tick_count": bar.get("tick_count", 0),
                                            "complete": True,
                                            "source": "stream_close",
                                        }
                                    )
                                result = file_cache.append_complete_bars(
                                    symbol=str(symbol),
                                    tf="1m",
                                    bars=cache_bars,
                                    now_utc=None,
                                    source="stream_close",
                                )
                                if result.duplicates > 0:
                                    status.append_error(
                                        code="cache_duplicate",
                                        severity="warn",
                                        message="File cache дубль open_time_ms",
                                        context={"symbol": symbol, "tf": "1m", "duplicates": result.duplicates},
                                    )
                                    status.mark_degraded("cache_duplicate")
                            except Exception as exc:  # noqa: BLE001
                                status.append_error(
                                    code="cache_write_failed",
                                    severity="error",
                                    message=str(exc),
                                    context={"symbol": symbol, "tf": "1m"},
                                )
                                status.mark_degraded("cache_write_failed")
                    last_open = int(bars[-1]["open_time"])
                    status.record_ohlcv_publish(
                        tf=str(payload.get("tf")),
                        bar_open_time_ms=last_open,
                        publish_ts_ms=now_ms,
                    )
                    ohlcv_publish_counts_by_tf[tf_name] = int(ohlcv_publish_counts_by_tf.get(tf_name, 0)) + 1
                    prev_open = int(ohlcv_last_open_by_tf.get(tf_name, 0))
                    if prev_open and prev_open != last_open:
                        ohlcv_prev_open_by_tf[tf_name] = prev_open
                    ohlcv_last_open_by_tf[tf_name] = int(last_open)
                    ohlcv_last_complete_by_tf[tf_name] = bool(payload.get("complete", False))

                    if ohlcv_last_complete_by_tf[tf_name]:
                        last_log = int(last_ohlcv_log_by_tf.get(tf_name, 0))
                        if now_ms - last_log >= 10_000:
                            log.info(
                                "Опубліковано final ohlcv tf=%s open_time_ms=%s",
                                tf_name,
                                last_open,
                            )
                            last_ohlcv_log_by_tf[tf_name] = now_ms

                    if now_ms - last_ohlcv_summary_log_ms >= 60_000:
                        preview_snapshot = status.snapshot().get("ohlcv_preview")
                        preview_state = preview_snapshot if isinstance(preview_snapshot, dict) else {}
                        snapshot = status.snapshot()
                        price_raw = snapshot.get("price")
                        fxcm_raw = snapshot.get("fxcm")
                        price = price_raw if isinstance(price_raw, dict) else {}
                        fxcm = fxcm_raw if isinstance(fxcm_raw, dict) else {}
                        last_publish_ts_ms = int(preview_state.get("last_publish_ts_ms", 0))
                        ohlcv_age_s = (now_ms - last_publish_ts_ms) / 1000.0 if last_publish_ts_ms > 0 else None
                        late_drop = int(preview_state.get("late_ticks_dropped_total", 0))
                        misalign = int(preview_state.get("misaligned_open_time_total", 0))
                        past_mut = int(preview_state.get("past_mutations_total", 0))
                        rails_changed = (late_drop, misalign, past_mut) != last_preview_rails
                        fxcm_state = str(fxcm.get("state", ""))
                        tick_lag_ms = int(price.get("tick_lag_ms", 0))
                        tick_lag_s = tick_lag_ms / 1000.0 if tick_lag_ms > 0 else 0.0
                        stale_tf = ""
                        stale_delay_bars = 0
                        parts = []
                        top_delay_parts = []
                        market_open = True
                        if calendar is not None:
                            market_open = bool(calendar.is_open(now_ms))
                        for tf_key, count in sorted(ohlcv_publish_counts_by_tf.items()):
                            tf_ms = TF_TO_MS.get(str(tf_key))
                            if tf_ms is None:
                                continue
                            last_open_ms = int(ohlcv_last_open_by_tf.get(tf_key, 0))
                            expected_ms = get_bucket_open_ms(str(tf_key), now_ms, calendar)
                            delay_bars = 0
                            if market_open:
                                grace_ms = 0
                                if str(tf_key) == "1m":
                                    grace_ms = 5_000
                                elif str(tf_key) == "15m":
                                    grace_ms = 60_000
                                expected_for_delay = int(expected_ms)
                                if grace_ms > 0 and now_ms - int(expected_ms) <= grace_ms:
                                    expected_for_delay = int(expected_ms) - int(tf_ms)
                                delay_bars = max(0, int((expected_for_delay - last_open_ms) // tf_ms))
                                if delay_bars >= stale_delay_bars:
                                    stale_delay_bars = delay_bars
                                    stale_tf = str(tf_key)
                                if delay_bars > 0:
                                    top_delay_parts.append(f"{tf_key}:delay={delay_bars}")
                            prev_open_ms = int(ohlcv_prev_open_by_tf.get(tf_key, 0))
                            step_ms = (last_open_ms - prev_open_ms) if prev_open_ms > 0 else 0
                            parts.append(
                                "{tf} last={last} expected={expected} delay={delay} step={step}s".format(
                                    tf=tf_key,
                                    last=_to_utc_iso(last_open_ms) if last_open_ms > 0 else "-",
                                    expected=_to_utc_iso(int(expected_ms))
                                    if (market_open and int(expected_ms) > 0)
                                    else "-",
                                    delay=delay_bars,
                                    step=int(step_ms / 1000) if step_ms > 0 else 0,
                                )
                            )
                        needs_summary = rails_changed or (
                            market_open and ohlcv_age_s is not None and ohlcv_age_s > 15.0
                        )
                        if stale_delay_bars > 0:
                            needs_summary = True
                        if parts and needs_summary:
                            tail = max(ohlcv_publish_counts_by_tf.values() or [0])
                            log.warning(
                                "OHLCV preview: %s tail=%s ohlcv_age=%.1fs fxcm=%s tick=%.1fs",
                                symbol,
                                tail,
                                float(ohlcv_age_s or 0.0),
                                fxcm_state,
                                tick_lag_s,
                            )
                            if stale_tf:
                                log.warning(
                                    "ohlcv_preview WARN stale_tf=%s delay_bars=%s expected=%s last=%s",
                                    stale_tf,
                                    stale_delay_bars,
                                    _to_utc_iso(int(get_bucket_open_ms(str(stale_tf), now_ms, calendar))),
                                    _to_utc_iso(int(ohlcv_last_open_by_tf.get(stale_tf, 0))),
                                )
                            if top_delay_parts:
                                log.warning("top_tf: %s", ", ".join(top_delay_parts[:4]))
                            log.warning(
                                "ohlcv_preview rails: late_drop=%s misalign=%s past_mut=%s",
                                late_drop,
                                misalign,
                                past_mut,
                            )
                        if (
                            parts
                            and not needs_summary
                            and ((not first_ok_summary_logged) or now_ms - last_ohlcv_summary_info_ms >= 300_000)
                        ):
                            tail = max(ohlcv_publish_counts_by_tf.values() or [0])
                            log.info(
                                "OHLCV preview OK: %s tail=%s ohlcv_age=%.1fs fxcm=%s tick=%.1fs",
                                symbol,
                                tail,
                                float(ohlcv_age_s or 0.0),
                                fxcm_state,
                                tick_lag_s,
                            )
                            last_ohlcv_summary_info_ms = now_ms
                            first_ok_summary_logged = True
                        last_ohlcv_summary_log_ms = now_ms
                        last_preview_rails = (late_drop, misalign, past_mut)
                        ohlcv_publish_counts_by_tf.clear()
                except ContractError as exc:
                    status.append_error(
                        code="ohlcv_preview_contract_error",
                        severity="error",
                        message=str(exc),
                        context={"symbol": symbol, "tf": payload.get("tf")},
                    )
                    status.record_ohlcv_error()
            preview_builder.mark_published(now_ms)
            status.publish_snapshot()

    fxcm_handle = None
    replay_handle = None
    if mode == BackendMode.FOREXCONNECT and config.tick_mode == "fxcm":
        fxcm_stream = FxcmForexConnectStream(config=config, status=status, on_tick=_handle_fxcm_tick)
        fxcm_handle = fxcm_stream.start()
        if fxcm_handle is None:
            status.publish_snapshot()
            raise SystemExit("FXCM tick stream не запущено")
    if mode == BackendMode.REPLAY:
        replay_stream = ReplayTickStream(
            config=config,
            validator=validator,
            calendar=calendar,
            status=status,
            on_tick=_handle_fxcm_tick,
        )
        replay_handle = replay_stream.start()

    ui_lite_handle = None
    if config.ui_lite_enabled:
        ui_lite_handle = start_ui_lite(config=config, redis_client=redis_client)
        log.info("UI Lite запущено на %s:%s", config.ui_lite_host, config.ui_lite_port)

    return RuntimeHandles(
        config=config,
        status=status,
        command_bus=command_bus,
        http_server=http_server,
        ui_lite_handle=ui_lite_handle,
        fxcm_handle=fxcm_handle,
        replay_handle=replay_handle,
        mode=mode,
    )


def stop_runtime(handles: RuntimeHandles) -> None:
    if handles.command_bus and handles.config.commands_enabled:
        handles.command_bus.stop()
    if handles.mode == BackendMode.FOREXCONNECT:
        if handles.fxcm_handle is not None:
            handles.fxcm_handle.stop()
    if handles.replay_handle is not None:
        handles.replay_handle.stop()
    handles.http_server.stop()
    if handles.ui_lite_handle is not None:
        handles.ui_lite_handle.stop()
