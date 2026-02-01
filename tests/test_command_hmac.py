from __future__ import annotations

import hmac
import os
import time
from hashlib import sha256
from pathlib import Path
from typing import Dict, Optional

from prometheus_client import CollectorRegistry

from config.config import Config
from core.time.calendar import Calendar
from core.validation.validator import SchemaValidator
from observability.metrics import create_metrics
from runtime.command_bus import CommandBus
from runtime.status import StatusManager


class InMemoryPublisher:
    def __init__(self) -> None:
        self.last_snapshot: Optional[str] = None
        self.last_channel: Optional[str] = None

    def set_snapshot(self, key: str, json_str: str) -> None:
        self.last_snapshot = json_str

    def publish(self, channel: str, json_str: str) -> None:
        self.last_channel = channel


class FakeRedis:
    def __init__(self) -> None:
        self._store: Dict[str, str] = {}

    def set(self, key: str, value: str, nx: bool = False, px: Optional[int] = None) -> bool:
        if nx and key in self._store:
            return False
        self._store[key] = value
        return True


def _build_status(config: Config) -> StatusManager:
    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)
    calendar = Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)
    metrics = create_metrics(CollectorRegistry())
    status = StatusManager(
        config=config,
        validator=validator,
        publisher=InMemoryPublisher(),
        calendar=calendar,
        metrics=metrics,
    )
    status.build_initial_snapshot()
    return status


def _sign_payload(payload: dict, kid: str, nonce: str, secret: str) -> str:
    canonical = {
        "cmd": str(payload.get("cmd", "")),
        "req_id": str(payload.get("req_id", "")),
        "ts": int(payload.get("ts", 0)),
        "args": payload.get("args", {}),
        "kid": kid,
        "nonce": nonce,
    }
    data = json_dumps_canonical(canonical)
    return hmac.new(secret.encode("utf-8"), data.encode("utf-8"), sha256).hexdigest()


def json_dumps_canonical(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_hmac_valid_signature_accepted() -> None:
    kid = "k1"
    secret = "s1"
    os.environ["FXCM_HMAC_KID"] = kid
    os.environ["FXCM_HMAC_SECRET"] = secret

    config = Config(
        command_auth_enable=True,
        command_auth_required=True,
        command_auth_allowed_kids=[kid],
    )
    status = _build_status(config)
    redis = FakeRedis()

    called = {"ok": False}

    def _handler(_payload: dict) -> None:
        called["ok"] = True

    bus = CommandBus(
        redis_client=redis,
        config=config,
        validator=status.validator,
        status=status,
        metrics=status.metrics,
        allowlist={"ping"},
        handlers={"ping": _handler},
    )

    ts_ms = int(time.time() * 1000)
    payload = {"cmd": "ping", "req_id": "r1", "ts": ts_ms, "args": {}}
    nonce = "n1"
    sig = _sign_payload(payload, kid=kid, nonce=nonce, secret=secret)
    payload["auth"] = {"kid": kid, "sig": sig, "nonce": nonce}

    bus.handle_payload(payload)

    assert called["ok"] is True


def test_hmac_invalid_signature_rejected_redacted() -> None:
    kid = "k1"
    secret = "s1"
    os.environ["FXCM_HMAC_KID"] = kid
    os.environ["FXCM_HMAC_SECRET"] = secret

    config = Config(
        command_auth_enable=True,
        command_auth_required=True,
        command_auth_allowed_kids=[kid],
    )
    status = _build_status(config)
    redis = FakeRedis()

    bus = CommandBus(
        redis_client=redis,
        config=config,
        validator=status.validator,
        status=status,
        metrics=status.metrics,
        allowlist={"ping"},
        handlers={"ping": lambda _payload: None},
    )

    ts_ms = int(time.time() * 1000)
    payload = {"cmd": "ping", "req_id": "r1", "ts": ts_ms, "args": {}}
    payload["auth"] = {"kid": kid, "sig": "bad", "nonce": "n1"}

    bus.handle_payload(payload)

    errors = status.snapshot().get("errors", [])
    assert errors
    last = errors[-1]
    assert last.get("code") == "auth_failed"
    assert last.get("message") == "Команда відхилена"


def test_replay_req_id_rejected_setnx_ttl() -> None:
    kid = "k1"
    secret = "s1"
    os.environ["FXCM_HMAC_KID"] = kid
    os.environ["FXCM_HMAC_SECRET"] = secret

    config = Config(
        command_auth_enable=True,
        command_auth_required=True,
        command_auth_allowed_kids=[kid],
        command_auth_replay_ttl_ms=60_000,
    )
    status = _build_status(config)
    redis = FakeRedis()

    bus = CommandBus(
        redis_client=redis,
        config=config,
        validator=status.validator,
        status=status,
        metrics=status.metrics,
        allowlist={"ping"},
        handlers={"ping": lambda _payload: None},
    )

    ts_ms = int(time.time() * 1000)
    payload = {"cmd": "ping", "req_id": "r1", "ts": ts_ms, "args": {}}
    nonce = "n1"
    sig = _sign_payload(payload, kid=kid, nonce=nonce, secret=secret)
    payload["auth"] = {"kid": kid, "sig": sig, "nonce": nonce}

    bus.handle_payload(payload)
    bus.handle_payload(payload)

    errors = status.snapshot().get("errors", [])
    assert errors
    last = errors[-1]
    assert last.get("code") == "replay_rejected"
    assert last.get("message") == "Команда відхилена"
