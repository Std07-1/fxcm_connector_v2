from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Dict, Mapping, Optional, Set

from config.config import Config
from core.validation.validator import ContractError, SchemaValidator
from observability.metrics import Metrics
from runtime.history_provider import ProviderNotConfiguredError
from runtime.status import StatusManager


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
        else:
            raw = str(data)
        self.handle_raw_message(raw)

    def handle_raw_message(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._status.append_error(
                code="invalid_json",
                severity="error",
                message=f"Некоректний JSON команди: {exc}",
            )
            self._status.set_last_command_error("unknown", "unknown", 0)
            self._status.publish_snapshot()
            return
        self.handle_payload(payload)

    def handle_payload(self, payload: Dict[str, Any]) -> None:
        try:
            self._validator.validate_commands_v1(payload)
        except ContractError as exc:
            cmd = str(payload.get("cmd", "unknown"))
            req_id = str(payload.get("req_id", "unknown"))
            self._status.append_error(
                code="contract_error",
                severity="error",
                message=str(exc),
            )
            self._status.set_last_command_error(cmd, req_id, int(payload.get("ts", 0)))
            self._status.publish_snapshot()
            if self._metrics is not None:
                self._metrics.commands_total.labels(cmd=cmd, state="error").inc()
            return

        cmd = str(payload.get("cmd"))
        req_id = str(payload.get("req_id"))
        started_ts = int(payload.get("ts", 0))

        if cmd not in self._allowlist:
            self._status.append_error(
                code="unknown_command",
                severity="error",
                message=f"Невідома команда: {cmd}",
                context={"cmd": cmd},
            )
            self._status.set_last_command_error(cmd, req_id, started_ts)
            self._status.publish_snapshot()
            if self._metrics is not None:
                self._metrics.commands_total.labels(cmd=cmd, state="error").inc()
            return

        handler = self._handlers.get(cmd)
        if handler is None:
            self._status.append_error(
                code="not_implemented",
                severity="error",
                message=f"Команда не реалізована у P3: {cmd}",
                context={"cmd": cmd},
            )
            self._status.set_last_command_error(cmd, req_id, started_ts)
            self._status.publish_snapshot()
            if self._metrics is not None:
                self._metrics.commands_total.labels(cmd=cmd, state="error").inc()
            return

        self._status.set_last_command_running(cmd, req_id, started_ts)
        try:
            handler(payload)
        except ProviderNotConfiguredError as exc:
            self._status.append_error(
                code="provider_not_configured",
                severity="error",
                message=str(exc),
            )
            self._status.set_last_command_error(cmd, req_id, started_ts)
            if self._metrics is not None:
                self._metrics.commands_total.labels(cmd=cmd, state="error").inc()
            self._status.publish_snapshot()
            raise SystemExit(str(exc))
        except ValueError as exc:
            self._status.append_error(
                code="invalid_args",
                severity="error",
                message=str(exc),
            )
            self._status.set_last_command_error(cmd, req_id, started_ts)
            if self._metrics is not None:
                self._metrics.commands_total.labels(cmd=cmd, state="error").inc()
        except Exception as exc:
            self._status.append_error(
                code="command_error",
                severity="error",
                message=str(exc),
            )
            self._status.set_last_command_error(cmd, req_id, started_ts)
            if self._metrics is not None:
                self._metrics.commands_total.labels(cmd=cmd, state="error").inc()
        else:
            self._status.set_last_command_ok(cmd, req_id, started_ts)
            if self._metrics is not None:
                self._metrics.commands_total.labels(cmd=cmd, state="ok").inc()
        self._status.publish_snapshot()
