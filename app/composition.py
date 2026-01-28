from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import redis

from config.config import Config
from core.runtime.mode import BackendMode
from core.time.calendar import Calendar
from core.validation.validator import ContractError, SchemaValidator
from observability.metrics import Metrics, create_metrics, start_metrics_server
from runtime.command_bus import CommandBus
from runtime.fxcm.history_budget import build_history_budget
from runtime.fxcm.history_provider import FxcmForexConnectHistoryAdapter, FxcmHistoryProvider
from runtime.fxcm_forexconnect import FxcmForexConnectHandle, FxcmForexConnectStream
from runtime.handlers_p3 import handle_backfill_command, handle_warmup_command
from runtime.handlers_p4 import handle_rebuild_derived_command, rebuild_derived_range
from runtime.history_provider import HistoryProvider, ProviderNotConfiguredError
from runtime.http_server import HttpServer
from runtime.no_mix import NoMixDetector
from runtime.ohlcv_preview import PreviewCandleBuilder, select_closed_bars_for_archive
from runtime.preview_builder import OhlcvCache
from runtime.publisher import RedisPublisher
from runtime.rebuild_derived import DerivedRebuildCoordinator
from runtime.replay_ticks import ReplayTickHandle, ReplayTickStream
from runtime.republish import republish_tail
from runtime.status import StatusManager
from runtime.tail_guard import run_tail_guard
from runtime.tick_feed import TickPublisher
from store.bars_store import BarsStoreSQLite
from store.file_cache.history_cache import HistoryCache
from store.live_archive_store import SqliteLiveArchiveStore
from store.sqlite_store import SQLiteStore
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
    if config.tick_mode != "off" or config.preview_mode != "off" or config.ohlcv_sim_enabled:
        raise SystemExit("Runtime sim-режими видалені: вимкніть tick/preview/ohlcv sim")


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

    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)

    store = SQLiteStore(db_path=Path(config.store_path))
    store.init_schema(root_dir / "store" / "schema.sql")
    bars_store = BarsStoreSQLite(db_path=Path(config.store_path), schema_path=root_dir / "store" / "schema.sql")

    redis_client = redis.Redis.from_url(config.redis_dsn(), decode_responses=True)
    no_mix = NoMixDetector()
    publisher = RedisPublisher(redis_client, config, no_mix=no_mix, status=None)

    metrics = None
    if config.metrics_enabled:
        metrics = create_metrics()
        start_metrics_server(config.metrics_port)
        log.info("/metrics піднято на порту %s", config.metrics_port)

    calendar = Calendar(
        closed_intervals_utc=config.closed_intervals_utc,
        calendar_tag=config.calendar_tag,
    )

    status = StatusManager(
        config=config,
        validator=validator,
        publisher=publisher,
        calendar=calendar,
        metrics=metrics,
    )
    status.build_initial_snapshot()
    publisher.set_status(status)

    live_archive_store: Optional[SqliteLiveArchiveStore] = None
    live_archive_disabled_reported = False
    if config.live_archive_enabled:
        try:
            live_archive_store = SqliteLiveArchiveStore(db_path=Path(config.live_archive_sqlite_path))
            live_archive_store.init_schema()
        except Exception as exc:  # noqa: BLE001
            status.append_error(
                code="live_archive_init_failed",
                severity="error",
                message=str(exc),
            )
            status.mark_degraded("live_archive_init_failed")
            status.publish_snapshot()
            raise SystemExit("LiveArchive ініціалізація не вдалася")
    else:
        status.mark_degraded("live_archive_disabled")
        if metrics is not None:
            metrics.live_archive_write_fail_total.inc()
        live_archive_disabled_reported = True

    file_cache_by_symbol: dict = {}
    file_cache_disabled_reported = False
    if not config.file_cache_enabled:
        status.mark_degraded("file_cache_disabled")
        status.append_error(
            code="file_cache_disabled",
            severity="warn",
            message="File cache вимкнений у конфігу",
        )
        file_cache_disabled_reported = True

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
    preview_builder = PreviewCandleBuilder(config=config, cache=cache, status=status)

    http_server = HttpServer(config=config, redis_client=redis_client, cache=cache, store=store)
    http_server.start()
    log.info("HTTP chart піднято на порту %s", config.http_port)

    derived_rebuilder = DerivedRebuildCoordinator()

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
        last_close = store.get_last_complete_close_ms(symbol)
        if last_close <= 0:
            return
        start_ms = last_close - window_hours * 60 * 60 * 1000 + 1
        t = start_ms
        while t <= last_close:
            bars = store.query_range(
                symbol=symbol,
                start_ms=t,
                end_ms=last_close,
                limit=config.max_bars_per_message,
            )
            if not bars:
                break
            payload_bars = []
            for b in bars:
                bar = {
                    "open_time": b["open_time_ms"],
                    "close_time": b["close_time_ms"],
                    "open": b["open"],
                    "high": b["high"],
                    "low": b["low"],
                    "close": b["close"],
                    "volume": b["volume"],
                    "complete": True,
                    "synthetic": False,
                    "source": "history",
                }
                event_ts = b.get("event_ts_ms")
                if event_ts is not None:
                    bar["event_ts"] = event_ts
                payload_bars.append(bar)
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
            t = int(bars[-1]["open_time_ms"]) + 60_000
        bars_total_est = store.count_1m_final(symbol)
        status.record_final_publish(
            last_complete_bar_ms=int(last_close),
            now_ms=int(time.time() * 1000),
            lookback_days=config.warmup_lookback_days,
            bars_total_est=bars_total_est,
        )
        status.publish_snapshot()

    def _rebuild_range_callback(symbol: str, start_ms: int, end_ms: int, tfs: List[str]) -> None:
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

    def _handle_warmup(payload: dict) -> None:
        args = payload.get("args", {})
        provider_name = str(args.get("provider", ""))
        provider = _select_provider(provider_name)
        handle_warmup_command(
            payload=payload,
            config=config,
            store=store,
            provider=provider,
            status=status,
            metrics=metrics,
            publish_tail=_publish_final_tail,
            rebuild_callback=_rebuild_range_callback,
        )

    def _handle_backfill(payload: dict) -> None:
        args = payload.get("args", {})
        provider_name = str(args.get("provider", ""))
        provider = _select_provider(provider_name)
        handle_backfill_command(
            payload=payload,
            config=config,
            store=store,
            provider=provider,
            status=status,
            metrics=metrics,
            publish_tail=_publish_final_tail,
            rebuild_callback=_rebuild_range_callback,
        )

    def _handle_rebuild_derived(payload: dict) -> None:
        handle_rebuild_derived_command(
            payload=payload,
            config=config,
            bars_store=bars_store,
            publisher=publisher,
            validator=validator,
            status=status,
            metrics=metrics,
        )

    def _handle_tail_guard(payload: dict) -> None:
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
                    store=store,
                    calendar=calendar,
                    provider=None,
                    redis_client=redis_client,
                    derived_rebuilder=derived_rebuilder,
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
                    store=store,
                    calendar=calendar,
                    provider=provider,
                    redis_client=redis_client,
                    derived_rebuilder=derived_rebuilder,
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
            store=store,
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
        "fxcm_rebuild_derived": _handle_rebuild_derived,
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
    last_archived_open_by_tf: dict = {}

    def _handle_fxcm_tick(
        symbol: str,
        bid: float,
        ask: float,
        mid: float,
        tick_ts_ms: int,
        snap_ts_ms: int,
    ) -> None:
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
                        for bar in closed_bars:
                            if live_archive_store is None:
                                if not live_archive_disabled_reported:
                                    status.append_error(
                                        code="live_archive_disabled",
                                        severity="warn",
                                        message="LiveArchive вимкнений у конфігу",
                                    )
                                    status.mark_degraded("live_archive_disabled")
                                    if metrics is not None:
                                        metrics.live_archive_write_fail_total.inc()
                                    live_archive_disabled_reported = True
                                break
                            result = live_archive_store.insert_bar(
                                symbol=str(payload.get("symbol")),
                                tf=tf_name,
                                open_time_ms=int(bar.get("open_time", 0)),
                                close_time_ms=int(bar.get("close_time", 0)),
                                payload=bar,
                            )
                            if result.status == "INSERTED":
                                if metrics is not None:
                                    metrics.live_archive_insert_total.inc()
                            elif result.status == "DUPLICATE":
                                if metrics is not None:
                                    metrics.live_archive_duplicate_total.inc()
                                status.append_error(
                                    code="live_archive_duplicate",
                                    severity="warn",
                                    message="LiveArchive дубль",
                                    context={"symbol": symbol, "tf": tf_name, "open_time_ms": bar.get("open_time")},
                                )
                            else:
                                if metrics is not None:
                                    metrics.live_archive_write_fail_total.inc()
                                status.append_error(
                                    code="live_archive_write_failed",
                                    severity="error",
                                    message=str(result.error or "write failed"),
                                    context={"symbol": symbol, "tf": tf_name, "open_time_ms": bar.get("open_time")},
                                )
                                status.mark_degraded("live_archive_write_failed")
                        if closed_bars:
                            last_archived_open_by_tf[tf_name] = int(closed_bars[-1].get("open_time", last_archived))
                    if tf_name == "1m" and closed_bars:
                        if not config.file_cache_enabled:
                            if not file_cache_disabled_reported:
                                status.append_error(
                                    code="file_cache_disabled",
                                    severity="warn",
                                    message="File cache вимкнений у конфігу",
                                )
                                status.mark_degraded("file_cache_disabled")
                                file_cache_disabled_reported = True
                        else:
                            try:
                                symbol_key = str(symbol)
                                cache = file_cache_by_symbol.get(symbol_key)
                                if cache is None:
                                    cache = HistoryCache(
                                        root=Path(config.file_cache_root),
                                        symbol=symbol_key,
                                        tf="1m",
                                        max_bars=int(config.file_cache_max_bars),
                                        warmup_bars=int(config.file_cache_warmup_bars),
                                    )
                                    file_cache_by_symbol[symbol_key] = cache
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
                                            "complete": True,
                                            "synthetic": bool(bar.get("synthetic", False)),
                                            "source": str(bar.get("source", "stream")),
                                            "event_ts": bar.get("close_time"),
                                        }
                                    )
                                result = cache.append_stream_bars(cache_bars)
                                if result.duplicates > 0:
                                    status.append_error(
                                        code="file_cache_duplicate",
                                        severity="warn",
                                        message="File cache дубль open_time_ms",
                                        context={
                                            "symbol": symbol,
                                            "tf": "1m",
                                            "duplicates": result.duplicates,
                                        },
                                    )
                                    status.mark_degraded("file_cache_duplicate")
                            except Exception as exc:  # noqa: BLE001
                                status.append_error(
                                    code="file_cache_write_failed",
                                    severity="error",
                                    message=str(exc),
                                    context={"symbol": symbol, "tf": "1m"},
                                )
                                status.mark_degraded("file_cache_write_failed")
                    last_open = int(bars[-1]["open_time"])
                    status.record_ohlcv_publish(
                        tf=str(payload.get("tf")),
                        bar_open_time_ms=last_open,
                        publish_ts_ms=now_ms,
                    )
                    last_log = int(last_ohlcv_log_by_tf.get(tf_name, 0))
                    if now_ms - last_log >= 10_000:
                        log.info(
                            "Опубліковано ohlcv tf=%s open_time_ms=%s complete=%s",
                            tf_name,
                            last_open,
                            str(payload.get("complete", False)).lower(),
                        )
                        last_ohlcv_log_by_tf[tf_name] = now_ms
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
    if mode == BackendMode.FOREXCONNECT:
        fxcm_stream = FxcmForexConnectStream(config=config, status=status, on_tick=_handle_fxcm_tick)
        fxcm_handle = fxcm_stream.start()
        if fxcm_preview and fxcm_handle is None:
            status.publish_snapshot()
            raise SystemExit("FXCM preview: stream не запущено")
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
