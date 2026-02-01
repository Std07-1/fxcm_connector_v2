from __future__ import annotations

import hmac
import json
import os
import time
from hashlib import sha256
from typing import Any, Dict, Optional, Tuple

from config.config import Config


def _load_secrets_from_module(profile: str) -> Tuple[Dict[str, str], Optional[str]]:
    if not profile:
        return {}, None
    module_name = f"config.secrets_{profile}"
    try:
        module = __import__(module_name, fromlist=["_dummy"])
    except ModuleNotFoundError:
        return {}, None
    secrets = {}
    default_kid = None
    if hasattr(module, "COMMAND_AUTH_SECRETS"):
        value = getattr(module, "COMMAND_AUTH_SECRETS")
        if isinstance(value, dict):
            secrets = {str(k): str(v) for k, v in value.items()}
    if hasattr(module, "COMMAND_AUTH_DEFAULT_KID"):
        default_kid = str(getattr(module, "COMMAND_AUTH_DEFAULT_KID"))
    return secrets, default_kid


def _load_secrets_from_env() -> Tuple[Dict[str, str], Optional[str]]:
    secret = os.environ.get("FXCM_HMAC_SECRET", "").strip()
    kid = os.environ.get("FXCM_HMAC_KID", "").strip()
    if secret and kid:
        return {kid: secret}, kid
    return {}, None


def _resolve_secrets(config: Config) -> Tuple[Dict[str, str], Optional[str]]:
    module_secrets, module_kid = _load_secrets_from_module(config.profile)
    env_secrets, env_kid = _load_secrets_from_env()
    merged = dict(module_secrets)
    merged.update(env_secrets)
    default_kid = env_kid or module_kid
    return merged, default_kid


def _canonical_payload(payload: Dict[str, Any], kid: str, nonce: str) -> str:
    data = {
        "cmd": str(payload.get("cmd", "")),
        "req_id": str(payload.get("req_id", "")),
        "ts": int(payload.get("ts", 0)),
        "args": payload.get("args", {}),
        "kid": kid,
        "nonce": nonce,
    }
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def verify_command_auth(
    payload: Dict[str, Any],
    config: Config,
    redis_client: Optional[Any],
) -> Tuple[bool, str]:
    auth = payload.get("auth")
    if not isinstance(auth, dict):
        return False, "auth_failed"

    kid = str(auth.get("kid", "")).strip()
    sig = str(auth.get("sig", "")).strip()
    nonce = str(auth.get("nonce", "")).strip()
    if not nonce:
        nonce = str(payload.get("req_id", "")).strip()

    if not kid or not sig or not nonce:
        return False, "auth_failed"

    allowed = list(config.command_auth_allowed_kids or [])
    if allowed and kid not in allowed:
        return False, "auth_failed"

    now_ms = int(time.time() * 1000)
    ts_ms = int(payload.get("ts", 0))
    max_skew = int(config.command_auth_max_skew_ms)
    if max_skew >= 0 and abs(now_ms - ts_ms) > max_skew:
        return False, "auth_ts_skew"

    secrets, _default = _resolve_secrets(config)
    secret = secrets.get(kid, "")
    if not secret:
        return False, "auth_failed"

    canonical = _canonical_payload(payload, kid=kid, nonce=nonce)
    expected = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False, "auth_failed"

    if redis_client is None:
        return False, "auth_failed"

    key = f"{config.ns}:cmd_replay:{kid}:{nonce}"
    ttl_ms = int(config.command_auth_replay_ttl_ms)
    try:
        ok = redis_client.set(key, "1", nx=True, px=ttl_ms)
    except Exception:
        return False, "auth_failed"
    if not ok:
        return False, "replay_rejected"
    return True, "ok"
