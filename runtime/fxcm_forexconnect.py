from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from typing_extensions import Protocol

from config.config import Config
from core.market.tick import Tick, normalize_tick
from core.time.sessions import _to_utc_iso
from core.time.timestamps import to_epoch_ms_utc
from core.validation.validator import ContractError
from observability.metrics import Metrics
from runtime.fxcm.adapter import FxcmAdapter
from runtime.fxcm.fsm import FxcmFsmDecision, FxcmSessionFsm
from runtime.fxcm.session_manager import FxcmSessionManager
from runtime.fxcm.tick_liveness import FxcmTickLiveness
from runtime.status import StatusManager

log = logging.getLogger("fxcm_forexconnect")


class _TickStatusSink(Protocol):
    metrics: Optional[Metrics]

    def append_error(
        self,
        code: str,
        severity: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None: ...

    def append_error_throttled(
        self,
        code: str,
        severity: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        throttle_key: Optional[str] = None,
        throttle_ms: int = 60_000,
        now_ms: Optional[int] = None,
        external_last_ts_by_key: Optional[Dict[str, int]] = None,
        external_lock: Optional[threading.Lock] = None,
    ) -> bool: ...

    def record_tick_drop_missing_event(self, now_ms: int) -> None: ...


@dataclass
class FxcmForexConnectHandle:
    thread: threading.Thread
    stop_event: threading.Event

    def stop(self) -> None:
        self.stop_event.set()
        try:
            self.thread.join(timeout=2.0)
        except KeyboardInterrupt:
            return


def _try_import_forexconnect() -> Tuple[Optional[Any], Optional[str]]:
    try:
        from forexconnect import ForexConnect  # type: ignore[import]

        return ForexConnect, None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def check_fxcm_environment(config: Config) -> Tuple[bool, str]:
    if config.fxcm_backend == "disabled":
        return False, "fxcm_disabled"
    if config.fxcm_backend == "replay":
        return True, "replay"
    if config.fxcm_backend != "forexconnect":
        return False, "fxcm_backend_not_supported"
    if not config.fxcm_username or not config.fxcm_password:
        return False, "fxcm_secrets_missing"
    fx_class, err = _try_import_forexconnect()
    if fx_class is None:
        return False, f"fxcm_sdk_missing: {err or 'unknown'}"
    return True, "ok"


def ensure_fxcm_ready(config: Config, status: StatusManager) -> bool:
    ok, reason = check_fxcm_environment(config)
    if ok:
        status.update_fxcm_state(
            state="connected",
            last_tick_ts_ms=0,
            last_err=None,
            last_ok_ts_ms=int(time.time() * 1000),
            reconnect_attempt=0,
            next_retry_ts_ms=0,
        )
        return True
    if reason == "fxcm_disabled":
        status.update_fxcm_state(
            state="disabled",
            last_tick_ts_ms=0,
            last_err=None,
            reconnect_attempt=0,
            next_retry_ts_ms=0,
        )
        return False
    if reason == "fxcm_secrets_missing":
        log.error("FXCM secrets відсутні у .env.local/.env.prod")
        status.append_error(
            code="fxcm_secrets_missing",
            severity="error",
            message="FXCM secrets відсутні у .env.local/.env.prod",
        )
        status.mark_degraded("fxcm_secrets_missing")
        err_ts = int(time.time() * 1000)
        status.update_fxcm_state(
            state="error",
            last_tick_ts_ms=0,
            last_err="fxcm_secrets_missing",
            last_err_ts_ms=err_ts,
            reconnect_attempt=0,
            next_retry_ts_ms=0,
        )
        return False
    if reason.startswith("fxcm_sdk_missing"):
        log.error("ForexConnect SDK недоступний")
        status.append_error(
            code="fxcm_sdk_missing",
            severity="error",
            message="ForexConnect SDK недоступний. Перевір forexconnect + DLL у PATH.",
        )
        status.mark_degraded("fxcm_sdk_missing")
        err_ts = int(time.time() * 1000)
        status.update_fxcm_state(
            state="error",
            last_tick_ts_ms=0,
            last_err="fxcm_sdk_missing",
            last_err_ts_ms=err_ts,
            reconnect_attempt=0,
            next_retry_ts_ms=0,
        )
        return False
    status.append_error(
        code="fxcm_backend_not_supported",
        severity="error",
        message=f"FXCM backend не підтримується: {config.fxcm_backend}",
    )
    status.mark_degraded("fxcm_backend_not_supported")
    err_ts = int(time.time() * 1000)
    status.update_fxcm_state(
        state="error",
        last_tick_ts_ms=0,
        last_err="fxcm_backend_not_supported",
        last_err_ts_ms=err_ts,
        reconnect_attempt=0,
        next_retry_ts_ms=0,
    )
    return False


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace("-", "").upper()


def denormalize_symbol(symbol: str) -> str:
    sym = normalize_symbol(symbol)
    if len(sym) == 6:
        return f"{sym[:3]}/{sym[3:]}"
    return symbol


def map_fxcm_tf(tf_label: str) -> str:
    mapping = {
        "m1": "1m",
        "m5": "5m",
        "m15": "15m",
        "H1": "1h",
        "H4": "4h",
        "D1": "1d",
    }
    return mapping.get(tf_label, tf_label)


def _extract_event_ts_ms(row: Any) -> Optional[int]:
    candidates = [
        "time",
        "timestamp",
        "tick_time",
        "tick_time_ms",
        "time_ms",
        "time_stamp",
        "event_time",
        "event_ts",
        "event_ts_ms",
        "last_update",
        "last_update_time",
    ]
    for key in candidates:
        value = getattr(row, key, None)
        if value is None and isinstance(row, dict):
            value = row.get(key)
        if value is None:
            continue
        try:
            return int(to_epoch_ms_utc(value))
        except Exception:
            continue
    return None


def _offer_row_to_tick(
    row: Any,
    allowed_symbols: Iterable[str],
    receipt_ms: int,
    status: _TickStatusSink,
    event_ahead_warn_state: Optional[Tuple[Dict[str, int], threading.Lock]] = None,
    event_ahead_throttle_ms: int = 60_000,
) -> Optional[Tick]:
    instrument = getattr(row, "instrument", None)
    if not instrument:
        try:
            row_type = f"{type(row).__module__}.{type(row).__name__}"
        except Exception:  # noqa: BLE001
            row_type = "unknown"
        try:
            has_instrument_caps = bool(hasattr(row, "Instrument"))
        except Exception:  # noqa: BLE001
            has_instrument_caps = False
        try:
            attrs = [item for item in dir(row) if not item.startswith("__")]
            attrs = attrs[:30]
        except Exception:  # noqa: BLE001
            attrs = []
        log.warning(
            "FXCM offers row без instrument: row_type=%s has_Instrument=%s attrs=%s",
            row_type,
            has_instrument_caps,
            attrs,
        )
        raise ContractError("instrument відсутній")
    symbol = normalize_symbol(str(instrument))
    if symbol not in allowed_symbols:
        return None
    bid = getattr(row, "bid", None)
    ask = getattr(row, "ask", None)
    if bid is None or ask is None:
        raise ContractError("bid/ask відсутні")
    event_ts_ms = _extract_event_ts_ms(row)
    if event_ts_ms is None:
        status.append_error(
            code="missing_tick_event_ts",
            severity="error",
            message="FXCM tick без event_ts",
            context={"symbol": symbol},
        )
        status.record_tick_drop_missing_event(receipt_ms)
        metrics = status.metrics
        if metrics is not None:
            metrics.fxcm_ticks_dropped_total.labels(reason="missing_event_ts").inc()
        return None
    snap_ts_ms = int(receipt_ms)
    if int(event_ts_ms) > int(snap_ts_ms):
        metrics = status.metrics
        if metrics is not None:
            metrics.fxcm_event_ahead_total.labels(symbol=symbol).inc()
        warn_state = event_ahead_warn_state
        last_by_symbol = warn_state[0] if warn_state is not None else None
        warn_lock = warn_state[1] if warn_state is not None else None
        status.append_error_throttled(
            code="fxcm_tick_event_ahead_of_receipt",
            severity="warning",
            message="FXCM tick event_ts_ms > receipt_ms; snap_ts_ms нормалізовано",
            context={
                "symbol": symbol,
                "tick_ts_ms": int(event_ts_ms),
                "snap_ts_ms": int(snap_ts_ms),
            },
            throttle_key=f"fxcm_tick_event_ahead_of_receipt:{symbol}",
            throttle_ms=int(event_ahead_throttle_ms),
            now_ms=int(receipt_ms),
            external_last_ts_by_key=last_by_symbol,
            external_lock=warn_lock,
        )
        snap_ts_ms = int(event_ts_ms)
    return normalize_tick(
        symbol=symbol,
        bid=float(bid),
        ask=float(ask),
        tick_ts_ms=int(event_ts_ms),
        snap_ts_ms=snap_ts_ms,
    )


def _stale_action(
    last_tick_ts_ms: int,
    last_ok_ts_ms: int,
    now_ms: int,
    stale_ms: int,
    resubscribe_attempted: bool,
    is_market_open: bool,
) -> str:
    """Legacy helper для рішення про resubscribe/reconnect (збережено для тестів)."""
    if not is_market_open:
        return "ok"
    base_ts = last_tick_ts_ms or last_ok_ts_ms
    if base_ts <= 0:
        return "ok"
    if now_ms - base_ts <= stale_ms:
        return "ok"
    return "reconnect" if resubscribe_attempted else "resubscribe"


def _loud_offers_subscription_error(status: StatusManager, err_ts: int, message: str) -> None:
    status.append_error(
        code="fxcm_offers_subscribe_failed",
        severity="error",
        message=message,
    )
    status.mark_degraded("fxcm_offers_subscribe_failed")
    status.update_fxcm_state(
        state="error",
        last_tick_ts_ms=0,
        last_err="fxcm_offers_subscribe_failed",
        last_err_ts_ms=err_ts,
    )
    status.publish_snapshot()


class FXCMOfferSubscription:
    def __init__(
        self,
        fx: Any,
        symbols: List[str],
        on_tick: Callable[[Tick], None],
        status: StatusManager,
    ) -> None:
        self._fx = fx
        self._symbols = [normalize_symbol(s) for s in symbols]
        self._on_tick = on_tick
        self._status = status
        self._offers_table = None
        self._listener = None

    def attach(self) -> bool:
        try:
            from forexconnect.common import Common  # type: ignore[import]
        except Exception as exc:  # noqa: BLE001
            log.debug("FXCM Common недоступний: %s", exc)
            return False
        try:
            self._offers_table = self._fx.get_table(self._fx.OFFERS)
        except Exception as exc:  # noqa: BLE001
            log.debug("FXCM OFFERS table недоступна: %s", exc)
            return False

        def _on_row(_listener: Any, _row_id: str, row: Any) -> None:
            now_ms = int(time.time() * 1000)
            try:
                tick = _offer_row_to_tick(
                    row,
                    self._symbols,
                    receipt_ms=now_ms,
                    status=self._status,
                    event_ahead_warn_state=(self._last_event_ahead_warn_ts_ms_by_symbol, self._event_ahead_warn_lock),
                    event_ahead_throttle_ms=self._event_ahead_throttle_ms,
                )
                if tick is None:
                    return
            except ContractError as exc:
                message = str(exc)
                context = {"source": "fxcm_offers"}
                if message == "instrument відсутній":
                    try:
                        context["row_type"] = f"{type(row).__module__}.{type(row).__name__}"
                    except Exception:  # noqa: BLE001
                        context["row_type"] = "unknown"
                self._status.append_error(
                    code="tick_contract_reject",
                    severity="error",
                    message=message,
                    context=context,
                )
                self._status.mark_degraded("tick_contract_reject")
                self._status.record_tick_contract_reject()
                self._status.record_fxcm_contract_reject()
                return
            log.debug("FXCM offer tick: %s bid=%s ask=%s", tick.symbol, tick.bid, tick.ask)
            try:
                self._on_tick(tick)
            except Exception as exc:  # noqa: BLE001
                self._status.append_error(
                    code="fxcm_publish_fail",
                    severity="error",
                    message=f"FXCM publish fail: {exc}",
                )
                self._status.mark_degraded("fxcm_publish_fail")
                self._status.record_fxcm_publish_fail()

        self._listener = Common.subscribe_table_updates(
            self._offers_table,
            on_add_callback=_on_row,
            on_change_callback=_on_row,
        )
        log.debug("FXCM OFFERS listener attached")
        return True

    def close(self) -> None:
        if self._listener is not None:
            try:
                self._listener.unsubscribe()
            except Exception:
                pass
        self._listener = None
        self._offers_table = None


def _backoff_seconds(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    delay: float = float(min(cap, base * (2**attempt)))
    jitter = random.uniform(0.0, delay * 0.2)
    return float(delay + jitter)


class FxcmReconnectRequested(RuntimeError):
    def __init__(self, backoff_s: float, reason: str) -> None:
        super().__init__(reason)
        self.backoff_s = float(backoff_s)
        self.reason = reason


@dataclass
class FxcmForexConnectStream:
    config: Config
    status: StatusManager
    on_tick: Callable[[str, float, float, float, int, int], None]

    _thread: Optional[threading.Thread] = None
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _event_ahead_warn_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _last_event_ahead_warn_ts_ms_by_symbol: Dict[str, int] = field(default_factory=dict, repr=False)
    _event_ahead_throttle_ms: int = 60_000

    def start(self) -> Optional[FxcmForexConnectHandle]:
        if not ensure_fxcm_ready(self.config, self.status):
            self.status.publish_snapshot()
            return None
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return FxcmForexConnectHandle(thread=self._thread, stop_event=self._stop_event)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.status.update_fxcm_state(
            state="stopped",
            last_tick_ts_ms=0,
            last_err=None,
            reconnect_attempt=0,
            next_retry_ts_ms=0,
        )

    def _calendar_next_open_ms(self, now_ms: int) -> int:
        fallback_ms = int(now_ms + 60_000)
        try:
            next_open_ms_raw = self.status.calendar.next_open_ms(now_ms)
        except Exception as exc:  # noqa: BLE001
            self.status.append_error(
                code="fxcm_calendar_next_open_invalid",
                severity="error",
                message=f"Calendar next_open_ms помилка: {exc}",
                context={"now_ms": int(now_ms)},
            )
            self.status.mark_degraded("fxcm_calendar_next_open_invalid")
            return fallback_ms
        try:
            next_open_ms = int(next_open_ms_raw)
        except Exception as exc:  # noqa: BLE001
            self.status.append_error(
                code="fxcm_calendar_next_open_invalid",
                severity="error",
                message=f"Calendar next_open_ms не число: {exc}",
                context={"now_ms": int(now_ms), "next_open_ms": next_open_ms_raw},
            )
            self.status.mark_degraded("fxcm_calendar_next_open_invalid")
            return fallback_ms
        if next_open_ms <= now_ms:
            self.status.append_error(
                code="fxcm_calendar_next_open_invalid",
                severity="error",
                message=("Calendar next_open_ms невалідний: " f"next_open_ms={next_open_ms} <= now_ms={now_ms}"),
                context={"now_ms": int(now_ms), "next_open_ms": int(next_open_ms)},
            )
            self.status.mark_degraded("fxcm_calendar_next_open_invalid")
            return fallback_ms
        return next_open_ms

    def _sleep_interruptible(self, sleep_ms: int, step_ms: int = 500) -> bool:
        remaining_ms = max(0, int(sleep_ms))
        step_ms = max(1, int(step_ms))
        while remaining_ms > 0:
            if self._stop_event.is_set():
                return True
            step = min(step_ms, remaining_ms)
            self._stop_event.wait(step / 1000.0)
            if self._stop_event.is_set():
                return True
            remaining_ms -= step
        return False

    def _run(self) -> None:
        ForexConnect, err = _try_import_forexconnect()
        if ForexConnect is None:
            err_ts = int(time.time() * 1000)
            self.status.append_error(
                code="fxcm_sdk_missing",
                severity="error",
                message=f"ForexConnect SDK недоступний: {err}",
            )
            self.status.update_fxcm_state(
                state="error",
                last_tick_ts_ms=0,
                last_err="fxcm_sdk_missing",
                last_err_ts_ms=err_ts,
                reconnect_attempt=0,
                next_retry_ts_ms=0,
            )
            self.status.publish_snapshot()
            return

        reconnect_attempt = 0
        last_ok_ts_ms = 0
        first_tick_logged = False
        last_tick_log_ms = 0
        fx = None
        fsm = FxcmSessionFsm(
            stale_s=int(self.config.fxcm_stale_s),
            resubscribe_retries=int(self.config.fxcm_resubscribe_retries),
            reconnect_backoff_s=float(self.config.fxcm_reconnect_backoff_s),
            reconnect_backoff_cap_s=float(self.config.fxcm_reconnect_backoff_cap_s),
        )
        liveness = FxcmTickLiveness(
            stale_s=int(self.config.fxcm_stale_s),
            cooldown_s=int(self.config.fxcm_reconnect_cooldown_s),
        )
        login_reason = "startup"
        normalized_symbols = [normalize_symbol(s) for s in self.config.fxcm_symbols]
        denormalized_symbols = [denormalize_symbol(s) for s in self.config.fxcm_symbols]
        log.debug(
            "FXCM symbols: raw=%s normalized=%s denormalized=%s",
            self.config.fxcm_symbols,
            normalized_symbols,
            denormalized_symbols,
        )
        log.debug(
            "FXCM tf map: m1->%s m5->%s m15->%s H1->%s H4->%s D1->%s",
            map_fxcm_tf("m1"),
            map_fxcm_tf("m5"),
            map_fxcm_tf("m15"),
            map_fxcm_tf("H1"),
            map_fxcm_tf("H4"),
            map_fxcm_tf("D1"),
        )
        while not self._stop_event.is_set():
            now_ms = int(time.time() * 1000)
            if not self.status.calendar.is_open(now_ms):
                self.status.clear_degraded("fxcm_stale_no_ticks")
                next_open_ms = self._calendar_next_open_ms(now_ms)
                reconnect_attempt += 1
                backoff_s = _backoff_seconds(reconnect_attempt, cap=float(self.config.fxcm_reconnect_backoff_cap_s))
                retry_ms = max(next_open_ms, int(now_ms + backoff_s * 1000))
                self.status.update_fxcm_state(
                    state="paused_market_closed",
                    last_tick_ts_ms=0,
                    last_err=None,
                    last_ok_ts_ms=last_ok_ts_ms,
                    reconnect_attempt=reconnect_attempt,
                    next_retry_ts_ms=retry_ms,
                )
                self.status.publish_snapshot()
                sleep_ms = max(1000, retry_ms - now_ms)
                if self._sleep_interruptible(min(sleep_ms, 30_000), step_ms=500):
                    return
                continue

            state = "connecting"
            self.status.update_fxcm_state(
                state=state,
                last_tick_ts_ms=0,
                last_err=None,
                last_ok_ts_ms=last_ok_ts_ms,
                reconnect_attempt=reconnect_attempt,
                next_retry_ts_ms=0,
                fsm_state=fsm.state.value,
                stale_seconds=fsm.stale_seconds,
                last_action=fsm.last_action,
            )
            self.status.publish_snapshot()
            try:
                fx = ForexConnect()
                log.debug(
                    "FXCM login request: connection=%s host=%s user=%s",
                    self.config.fxcm_connection,
                    self.config.fxcm_host_url,
                    self.config.fxcm_username,
                )
                log.info(
                    "FXCM login component=stream reason=%s connection=%s host=%s",
                    login_reason,
                    self.config.fxcm_connection,
                    self.config.fxcm_host_url,
                )
                fx.login(
                    self.config.fxcm_username,
                    self.config.fxcm_password,
                    self.config.fxcm_host_url,
                    self.config.fxcm_connection,
                    "",
                    "",
                )
                last_ok_ts_ms = int(time.time() * 1000)
                reconnect_attempt = 0
                fsm.on_connected(last_ok_ts_ms)
                self.status.update_fxcm_state(
                    state="connected",
                    last_tick_ts_ms=0,
                    last_err=None,
                    last_ok_ts_ms=last_ok_ts_ms,
                    reconnect_attempt=reconnect_attempt,
                    next_retry_ts_ms=0,
                    fsm_state=fsm.state.value,
                    stale_seconds=fsm.stale_seconds,
                    last_action=fsm.last_action,
                )
                self.status.publish_snapshot()
                log.info("FXCM login успішний component=stream reason=%s", login_reason)
                last_tick_ts_ms = 0

                class _LiveAdapter(FxcmAdapter):
                    def __init__(self, subscription: FXCMOfferSubscription, status: StatusManager) -> None:
                        self._subscription = subscription
                        self._status = status

                    def resubscribe_offers(self) -> bool:
                        self._subscription.close()
                        return self._subscription.attach()

                    def reconnect(self) -> bool:
                        return True

                    def is_market_open(self, now_ms: int) -> bool:
                        return self._status.calendar.is_open(now_ms)

                session: Optional[FxcmSessionManager] = None

                def _on_offer_tick(tick: Tick) -> None:
                    nonlocal last_tick_ts_ms, first_tick_logged, last_tick_log_ms
                    last_tick_ts_ms = tick.tick_ts_ms
                    self.on_tick(
                        tick.symbol,
                        tick.bid,
                        tick.ask,
                        tick.mid,
                        tick.tick_ts_ms,
                        tick.snap_ts_ms,
                    )
                    if session is not None:
                        session.on_tick(tick.tick_ts_ms)
                    now_ms = int(time.time() * 1000)
                    if not first_tick_logged or now_ms - last_tick_log_ms >= 60_000:
                        first_tick_logged = True
                        last_tick_log_ms = now_ms
                        log.debug(
                            "FXCM tick OK: %s ts=%s",
                            tick.symbol,
                            _to_utc_iso(int(tick.tick_ts_ms)),
                        )

                subscription = FXCMOfferSubscription(
                    fx=fx,
                    symbols=self.config.fxcm_symbols,
                    on_tick=_on_offer_tick,
                    status=self.status,
                )
                adapter = _LiveAdapter(subscription=subscription, status=self.status)
                session = FxcmSessionManager(
                    fsm=fsm,
                    status=self.status,
                    adapter=adapter,
                    liveness=liveness,
                    metrics=self.status.metrics,
                )
                if not subscription.attach():
                    err_ts = int(time.time() * 1000)
                    _loud_offers_subscription_error(
                        status=self.status,
                        err_ts=err_ts,
                        message="FXCM OFFERS subscription не піднято",
                    )
                    raise RuntimeError("fxcm_offers_subscribe_failed")

                self.status.update_fxcm_state(
                    state="subscribed_offers",
                    last_tick_ts_ms=0,
                    last_err=None,
                    last_ok_ts_ms=last_ok_ts_ms,
                    reconnect_attempt=reconnect_attempt,
                    next_retry_ts_ms=0,
                    fsm_state=fsm.state.value,
                    stale_seconds=fsm.stale_seconds,
                    last_action=fsm.last_action,
                )
                self.status.publish_snapshot()
                if session is not None:
                    session.on_offers_subscribed(int(time.time() * 1000))

                while not self._stop_event.is_set():
                    now_ms = int(time.time() * 1000)
                    if not self.status.calendar.is_open(now_ms):
                        self.status.clear_degraded("fxcm_stale_no_ticks")
                        next_open_ms = self._calendar_next_open_ms(now_ms)
                        retry_ms = max(next_open_ms, int(now_ms + 1000))
                        self.status.update_fxcm_state(
                            state="paused_market_closed",
                            last_tick_ts_ms=last_tick_ts_ms,
                            last_err=None,
                            last_ok_ts_ms=last_ok_ts_ms,
                            reconnect_attempt=reconnect_attempt,
                            next_retry_ts_ms=retry_ms,
                            fsm_state=fsm.state.value,
                            stale_seconds=fsm.stale_seconds,
                            last_action=fsm.last_action,
                        )
                        self.status.publish_snapshot()
                        sleep_ms = max(1000, retry_ms - now_ms)
                        if self._sleep_interruptible(min(sleep_ms, 30_000), step_ms=500):
                            return
                        break
                    decision = session.on_timer(now_ms) if session is not None else FxcmFsmDecision(action=None)
                    if decision.action == "resubscribe":
                        if not adapter.resubscribe_offers():
                            err_ts = int(time.time() * 1000)
                            _loud_offers_subscription_error(
                                status=self.status,
                                err_ts=err_ts,
                                message="FXCM OFFERS resubscribe не вдалось",
                            )
                            if session is not None:
                                reconnect_decision = session.on_resubscribe_result(False)
                            else:
                                reconnect_decision = decision
                            raise FxcmReconnectRequested(
                                backoff_s=reconnect_decision.backoff_s,
                                reason=reconnect_decision.reason or "fxcm_offers_resubscribe_failed",
                            )
                        if session is not None:
                            session.on_resubscribe_result(True)
                    elif decision.action == "reconnect":
                        next_retry_ts_ms = int(now_ms + float(decision.backoff_s) * 1000)
                        self.status.update_fxcm_state(
                            state="reconnecting",
                            last_tick_ts_ms=last_tick_ts_ms,
                            last_err="fxcm_stale_no_ticks",
                            last_err_ts_ms=int(time.time() * 1000),
                            last_ok_ts_ms=last_ok_ts_ms,
                            reconnect_attempt=reconnect_attempt,
                            next_retry_ts_ms=next_retry_ts_ms,
                            fsm_state=fsm.state.value,
                            stale_seconds=fsm.stale_seconds,
                            last_action=fsm.last_action,
                        )
                        self.status.publish_snapshot()
                        raise FxcmReconnectRequested(
                            backoff_s=decision.backoff_s,
                            reason=decision.reason or "fxcm_stale_no_ticks",
                        )
                    time.sleep(0.5)
            except FxcmReconnectRequested as exc:
                reconnect_attempt += 1
                sleep_s = float(exc.backoff_s)
                login_reason = exc.reason or "reconnect"
                next_retry_ts_ms = int(time.time() * 1000 + sleep_s * 1000)
                err_ts = int(time.time() * 1000)
                self.status.append_error(
                    code="fxcm_reconnect_requested",
                    severity="error",
                    message=f"FXCM reconnect: {exc.reason}",
                )
                self.status.update_fxcm_state(
                    state="reconnecting",
                    last_tick_ts_ms=0,
                    last_err="fxcm_reconnect_requested",
                    last_err_ts_ms=err_ts,
                    last_ok_ts_ms=last_ok_ts_ms,
                    reconnect_attempt=reconnect_attempt,
                    next_retry_ts_ms=next_retry_ts_ms,
                    fsm_state=fsm.state.value,
                    stale_seconds=fsm.stale_seconds,
                    last_action=fsm.last_action,
                )
                self.status.publish_snapshot()
                time.sleep(sleep_s)
            except Exception as exc:  # noqa: BLE001
                reconnect_attempt += 1
                sleep_s = _backoff_seconds(reconnect_attempt, cap=float(self.config.fxcm_reconnect_backoff_cap_s))
                login_reason = "reconnect"
                next_retry_ts_ms = int(time.time() * 1000 + sleep_s * 1000)
                err_ts = int(time.time() * 1000)
                self.status.append_error(
                    code="fxcm_stream_error",
                    severity="error",
                    message=f"FXCM stream помилка: {exc}",
                )
                self.status.update_fxcm_state(
                    state="reconnecting",
                    last_tick_ts_ms=0,
                    last_err="fxcm_stream_error",
                    last_err_ts_ms=err_ts,
                    last_ok_ts_ms=last_ok_ts_ms,
                    reconnect_attempt=reconnect_attempt,
                    next_retry_ts_ms=next_retry_ts_ms,
                    fsm_state=fsm.state.value,
                    stale_seconds=fsm.stale_seconds,
                    last_action=fsm.last_action,
                )
                self.status.publish_snapshot()
                time.sleep(sleep_s)
            finally:
                if "subscription" in locals() and subscription is not None:
                    try:
                        subscription.close()
                    except Exception:
                        pass
                if fx is not None and hasattr(fx, "logout"):
                    try:
                        fx.logout()
                    except Exception:
                        pass
                fx = None
