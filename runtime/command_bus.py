from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, Mapping, Optional, Set

from config.config import Config
from core.validation.validator import ContractError, SchemaValidator
from observability.metrics import Metrics
from runtime.command_auth import verify_command_auth
from runtime.history_provider import ProviderNotConfiguredError
from runtime.status import StatusManager

PUBLIC_MSG_REJECTED = "Команда відхилена"
PUBLIC_MSG_INVALID = "Некоректна команда"
PUBLIC_MSG_LIMIT = "Перевищено ліміт"


class TokenBucket:
    def __init__(self, rate_per_s: float, burst: float) -> None:
        self._rate_per_s = max(0.0, float(rate_per_s))
        self._capacity = max(1.0, float(burst))
        self._tokens = self._capacity
        self._last_ts = time.monotonic()

    def allow(self, tokens: float = 1.0) -> bool:
        now = time.monotonic()
        elapsed = max(0.0, now - self._last_ts)
        self._last_ts = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate_per_s)
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False


class CommandBus:
    """Pub/Sub subscriber для {NS}:commands."""

    def __init__(
        self,
        redis_client: Optional[Any],
        config: Config,
        validator: SchemaValidator,
        status: StatusManager,
        metrics: Optional[Metrics] = None,
        allowlist: Optional[Set[str]] = None,
        handlers: Optional[Mapping[str, Callable[[Dict[str, Any]], None]]] = None,
    ) -> None:
        self._redis = redis_client
        self._config = config
        self._validator = validator
        self._status = status
        self._metrics = metrics
        self._allowlist = allowlist or set()
        self._handlers = dict(handlers or {})
        self._channel = self._config.ch_commands()
        self._pubsub = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_heartbeat_ts = 0.0
        self._raw_rate_bucket: Optional[TokenBucket] = None
        self._cmd_rate_buckets: Dict[str, TokenBucket] = {}
        self._heavy_inflight: Set[str] = set()
        self._heavy_pending: Dict[str, Dict[str, Any]] = {}
        self._heavy_cmds = set(self._config.command_heavy_cmds)
        if self._config.command_rate_limit_enable:
            self._raw_rate_bucket = TokenBucket(
                rate_per_s=float(self._config.command_rate_limit_raw_per_s),
                burst=float(self._config.command_rate_limit_raw_burst),
            )

    def start(self) -> bool:
        try:
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, name="command_bus", daemon=True)
            self._thread.start()
        except Exception as exc:
            self._status.append_error(
                code="command_bus_error",
                severity="error",
                message=f"Не вдалося запустити thread command_bus: {exc}",
            )
            self._status.update_command_bus_error(
                channel=self._channel,
                code="command_bus_error",
                message=f"Thread start fail: {exc}",
            )
            self._status.publish_snapshot()
            return False
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._pubsub is not None:
            try:
                self._pubsub.close()
            except Exception:
                pass

    def _run_loop(self) -> None:
        if self._redis is None:
            self._status.append_error(
                code="command_bus_error",
                severity="error",
                message="Redis клієнт для command_bus не налаштований",
            )
            self._status.update_command_bus_error(
                channel=self._channel,
                code="command_bus_error",
                message="Redis клієнт для command_bus не налаштований",
            )
            self._status.publish_snapshot()
            return
        try:
            pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(self._channel)
            self._pubsub = pubsub
        except Exception as exc:
            self._status.append_error(
                code="command_bus_error",
                severity="error",
                message=f"Не вдалося підписатися на {self._channel}: {exc}",
            )
            self._status.update_command_bus_error(
                channel=self._channel,
                code="command_bus_error",
                message=f"Subscribe fail: {exc}",
            )
            self._status.publish_snapshot()
            return

        self._last_heartbeat_ts = time.time()
        self._status.update_command_bus_heartbeat(self._channel)
        self._status.publish_snapshot()

        try:
            while not self._stop_event.is_set():
                self._maybe_heartbeat()
                if self._pubsub is None:
                    time.sleep(0.2)
                    continue
                try:
                    message = self._pubsub.get_message(timeout=1.0)
                except BaseException as exc:
                    self._status.append_error(
                        code="command_bus_error",
                        severity="error",
                        message=f"Помилка Pub/Sub: {exc}",
                    )
                    self._status.update_command_bus_error(
                        channel=self._channel,
                        code="command_bus_error",
                        message=f"Pub/Sub error: {exc}",
                    )
                    self._status.publish_snapshot()
                    time.sleep(0.5)
                    continue
                if not message:
                    continue
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    raw = data.decode("utf-8")
                    self.handle_raw_message(raw, raw_bytes_len=len(data))
                else:
                    raw = str(data)
                    self.handle_raw_message(raw)
        finally:
            if self._pubsub is not None:
                try:
                    self._pubsub.close()
                except Exception:
                    pass

    def _maybe_heartbeat(self) -> None:
        now = time.time()
        period = max(1, int(self._config.command_bus_heartbeat_period_s))
        if now - self._last_heartbeat_ts >= period:
            self._last_heartbeat_ts = now
            self._status.update_command_bus_heartbeat(self._channel)

    def poll(self, timeout_s: float) -> None:
        if self._pubsub is None:
            return
        try:
            message = self._pubsub.get_message(timeout=timeout_s)
        except BaseException as exc:
            self._status.append_error(
                code="redis_pubsub_error",
                severity="error",
                message=f"Помилка Pub/Sub: {exc}",
            )
            self._status.publish_snapshot()
            return
        if not message:
            return
        if message.get("type") != "message":
            return
        data = message.get("data")
        if isinstance(data, bytes):
            raw = data.decode("utf-8")
            self.handle_raw_message(raw, raw_bytes_len=len(data))
        else:
            raw = str(data)
            self.handle_raw_message(raw)

    def handle_raw_message(self, raw: str, raw_bytes_len: Optional[int] = None) -> None:
        if self._is_raw_rate_limited():
            self._append_public_error_coalesced(
                code="rate_limited",
                public_message=PUBLIC_MSG_LIMIT,
                coalesce_key="rate_limited_raw",
            )
            self._status.set_last_command_error("unknown", "unknown", 0)
            if self._metrics is not None:
                self._metrics.commands_rate_limited_total.labels(scope="raw").inc()
                self._metrics.commands_dropped_total.labels(reason="rate_limited_raw").inc()
            self._status.publish_snapshot()
            return
        payload_size = int(raw_bytes_len) if raw_bytes_len is not None else len(raw.encode("utf-8"))
        max_payload = int(self._config.max_command_payload_bytes)
        if max_payload > 0 and payload_size > max_payload:
            self._status.append_public_error(
                code="command_payload_too_large",
                severity="error",
                public_message=PUBLIC_MSG_LIMIT,
            )
            self._status.set_last_command_error("unknown", "unknown", 0)
            if self._metrics is not None:
                self._metrics.commands_dropped_total.labels(reason="payload_too_large").inc()
            self._status.publish_snapshot()
            return
        stripped = raw.lstrip()
        if not stripped or not stripped.startswith("{"):
            self._status.append_public_error(
                code="invalid_prefix",
                severity="error",
                public_message=PUBLIC_MSG_INVALID,
            )
            self._status.set_last_command_error("unknown", "unknown", 0)
            if self._metrics is not None:
                self._metrics.commands_dropped_total.labels(reason="invalid_prefix").inc()
            self._status.publish_snapshot()
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._append_public_error_coalesced(
                code="invalid_json",
                public_message=PUBLIC_MSG_INVALID,
                coalesce_key="invalid_json",
            )
            self._status.set_last_command_error("unknown", "unknown", 0)
            if self._metrics is not None:
                self._metrics.commands_dropped_total.labels(reason="invalid_json").inc()
            self._status.publish_snapshot()
            return
        self.handle_payload(payload)

    def handle_payload(self, payload: Dict[str, Any]) -> None:
        try:
            self._validator.validate_commands_v1(payload)
        except ContractError:
            cmd = str(payload.get("cmd", "unknown"))
            req_id = str(payload.get("req_id", "unknown"))
            self._append_public_error_coalesced(
                code="contract_error",
                public_message=PUBLIC_MSG_INVALID,
                coalesce_key="contract_error",
            )
            self._status.set_last_command_error(cmd, req_id, int(payload.get("ts", 0)))
            self._status.publish_snapshot()
            if self._metrics is not None:
                self._metrics.commands_total.labels(cmd=cmd, state="error").inc()
            return

        cmd = str(payload.get("cmd"))
        req_id = str(payload.get("req_id"))
        started_ts = int(payload.get("ts", 0))

        log = logging.getLogger("command_bus")

        auth_required = bool(self._config.command_auth_required)
        auth_enabled = bool(self._config.command_auth_enable) or auth_required
        if auth_enabled:
            auth_obj = payload.get("auth")
            if not isinstance(auth_obj, dict):
                if auth_required:
                    self._append_public_error_coalesced(
                        code="auth_failed",
                        public_message=PUBLIC_MSG_REJECTED,
                        coalesce_key="auth_failed",
                    )
                    self._status.set_last_command_error(cmd, req_id, started_ts)
                    if self._metrics is not None:
                        self._metrics.commands_dropped_total.labels(reason="auth_missing").inc()
                        self._metrics.commands_total.labels(cmd=cmd, state="error").inc()
                    self._status.publish_snapshot()
                    return
            else:
                ok, code = verify_command_auth(payload, self._config, self._redis)
                if not ok:
                    self._append_public_error_coalesced(
                        code=code,
                        public_message=PUBLIC_MSG_REJECTED,
                        coalesce_key=code,
                    )
                    self._status.set_last_command_error(cmd, req_id, started_ts)
                    if self._metrics is not None:
                        self._metrics.commands_dropped_total.labels(reason=code).inc()
                        self._metrics.commands_total.labels(cmd=cmd, state="error").inc()
                    self._status.publish_snapshot()
                    return

        if self._is_cmd_rate_limited(cmd):
            self._append_public_error_coalesced(
                code="rate_limited",
                public_message=PUBLIC_MSG_LIMIT,
                coalesce_key=f"rate_limited:{cmd}",
            )
            self._status.set_last_command_error(cmd, req_id, started_ts)
            if self._metrics is not None:
                self._metrics.commands_rate_limited_total.labels(scope="cmd").inc()
                self._metrics.commands_dropped_total.labels(reason="rate_limited_cmd").inc()
            self._status.publish_snapshot()
            return

        if cmd not in self._allowlist:
            self._status.append_public_error(
                code="unknown_command",
                severity="error",
                public_message=PUBLIC_MSG_REJECTED,
            )
            self._status.set_last_command_error(cmd, req_id, started_ts)
            self._status.publish_snapshot()
            if self._metrics is not None:
                self._metrics.commands_total.labels(cmd=cmd, state="error").inc()
            return

        handler = self._handlers.get(cmd)
        if handler is None:
            self._status.append_public_error(
                code="not_implemented",
                severity="error",
                public_message=PUBLIC_MSG_REJECTED,
            )
            self._status.set_last_command_error(cmd, req_id, started_ts)
            log.info("COMMAND end cmd=%s req_id=%s state=error", cmd, req_id)
            self._status.publish_snapshot()
            if self._metrics is not None:
                self._metrics.commands_total.labels(cmd=cmd, state="error").inc()
            return

        if self._config.command_heavy_collapse_enable and cmd in self._heavy_cmds:
            self._handle_heavy_command(payload, handler, log)
            return

        self._execute_handler(payload, handler, log)

    def _execute_handler(
        self, payload: Dict[str, Any], handler: Callable[[Dict[str, Any]], None], log: logging.Logger
    ) -> None:
        cmd = str(payload.get("cmd", "unknown"))
        req_id = str(payload.get("req_id", "unknown"))
        started_ts = int(payload.get("ts", 0))
        self._status.set_last_command_running(cmd, req_id, started_ts)
        log.info("COMMAND start cmd=%s req_id=%s", cmd, req_id)
        try:
            handler(payload)
        except ProviderNotConfiguredError as exc:
            self._status.append_public_error(
                code="provider_not_configured",
                severity="error",
                public_message=PUBLIC_MSG_REJECTED,
            )
            self._status.set_last_command_error(cmd, req_id, started_ts)
            if self._metrics is not None:
                self._metrics.commands_total.labels(cmd=cmd, state="error").inc()
            self._status.publish_snapshot()
            log.info("COMMAND end cmd=%s req_id=%s state=error", cmd, req_id)
            raise SystemExit(str(exc))
        except ValueError:
            self._status.append_public_error(
                code="invalid_args",
                severity="error",
                public_message=PUBLIC_MSG_INVALID,
            )
            self._status.set_last_command_error(cmd, req_id, started_ts)
            if self._metrics is not None:
                self._metrics.commands_total.labels(cmd=cmd, state="error").inc()
            log.info("COMMAND end cmd=%s req_id=%s state=error", cmd, req_id)
        except Exception:
            self._status.append_public_error(
                code="command_error",
                severity="error",
                public_message=PUBLIC_MSG_REJECTED,
            )
            self._status.set_last_command_error(cmd, req_id, started_ts)
            if self._metrics is not None:
                self._metrics.commands_total.labels(cmd=cmd, state="error").inc()
            log.info("COMMAND end cmd=%s req_id=%s state=error", cmd, req_id)
        else:
            self._status.set_last_command_ok(cmd, req_id, started_ts)
            if self._metrics is not None:
                self._metrics.commands_total.labels(cmd=cmd, state="ok").inc()
            log.info("COMMAND end cmd=%s req_id=%s state=ok", cmd, req_id)
        self._status.publish_snapshot()

    def _handle_heavy_command(
        self,
        payload: Dict[str, Any],
        handler: Callable[[Dict[str, Any]], None],
        log: logging.Logger,
    ) -> None:
        cmd = str(payload.get("cmd", "unknown"))
        if cmd in self._heavy_inflight:
            self._heavy_pending[cmd] = payload
            self._append_public_error_coalesced(
                code="command_collapsed",
                public_message=PUBLIC_MSG_LIMIT,
                coalesce_key=f"command_collapsed:{cmd}",
            )
            if self._metrics is not None:
                self._metrics.commands_dropped_total.labels(reason="heavy_collapsed").inc()
            self._status.publish_snapshot()
            return

        current_payload = payload
        while True:
            self._heavy_inflight.add(cmd)
            try:
                self._execute_handler(current_payload, handler, log)
            finally:
                self._heavy_inflight.discard(cmd)
            pending = self._heavy_pending.pop(cmd, None)
            if pending is None:
                break
            current_payload = pending

    def _append_public_error_coalesced(
        self,
        code: str,
        public_message: str,
        coalesce_key: str,
    ) -> None:
        if self._config.command_coalesce_enable:
            appended = self._status.append_public_error_coalesced(
                code=code,
                severity="error",
                public_message=public_message,
                coalesce_key=coalesce_key,
                window_s=int(self._config.command_coalesce_window_s),
            )
            if not appended and self._metrics is not None:
                self._metrics.commands_coalesced_total.labels(reason=coalesce_key).inc()
            return
        self._status.append_public_error(code=code, severity="error", public_message=public_message)

    def _is_raw_rate_limited(self) -> bool:
        if not self._config.command_rate_limit_enable:
            return False
        if self._raw_rate_bucket is None:
            self._raw_rate_bucket = TokenBucket(
                rate_per_s=float(self._config.command_rate_limit_raw_per_s),
                burst=float(self._config.command_rate_limit_raw_burst),
            )
        return not self._raw_rate_bucket.allow()

    def _is_cmd_rate_limited(self, cmd: str) -> bool:
        if not self._config.command_rate_limit_enable:
            return False
        bucket = self._cmd_rate_buckets.get(cmd)
        if bucket is None:
            bucket = TokenBucket(
                rate_per_s=float(self._config.command_rate_limit_cmd_per_s),
                burst=float(self._config.command_rate_limit_cmd_burst),
            )
            self._cmd_rate_buckets[cmd] = bucket
        return not bucket.allow()
