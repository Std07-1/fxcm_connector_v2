from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, Set

ALLOWED_ENV_KEYS: Set[str] = {
    "AI_ONE_ENV_FILE",
    "FXCM_CACHE_ENABLED",
    "FXCM_HMAC_SECRET",
    "FXCM_HMAC_ALGO",
    "FXCM_HMAC_REQUIRED",
    "FXCM_USERNAME",
    "FXCM_PASSWORD",
    "FXCM_CONNECTION",
    "FXCM_HOST_URL",
    "FXCM_CHANNEL_PREFIX",
    "FXCM_COMMANDS_CHANNEL",
    "FXCM_STATUS_CHANNEL",
    "FXCM_PRICE_SNAPSHOT_CHANNEL",
    "FXCM_OHLCV_CHANNEL",
    "FXCM_HEARTBEAT_CHANNEL",
    "FXCM_REDIS_HOST",
    "FXCM_REDIS_PORT",
    "FXCM_REDIS_PASSWORD",
    "FXCM_REDIS_REQUIRED",
    "FXCM_METRICS_ENABLED",
    "FXCM_METRICS_PORT",
}


def _parse_env_file(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    data: Dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        data[key] = value
    return data


def _validate_allowlist(keys: Iterable[str], allowlist: Set[str]) -> None:
    for key in keys:
        if key not in allowlist:
            raise RuntimeError(f"unknown env key: {key}")


def load_env(root_dir: Path) -> Dict[str, str]:
    env_path = root_dir / ".env"
    base_env = _parse_env_file(env_path)
    for key in base_env.keys():
        if key != "AI_ONE_ENV_FILE":
            raise RuntimeError(f"unknown env key: {key}")
    switch = os.environ.get("AI_ONE_ENV_FILE") or base_env.get("AI_ONE_ENV_FILE", "")
    merged = dict(base_env)
    if switch:
        switch_path = Path(switch)
        if not switch_path.is_absolute():
            switch_path = root_dir / switch_path
        merged.update(_parse_env_file(switch_path))
    _validate_allowlist(merged.keys(), ALLOWED_ENV_KEYS)
    for key, value in merged.items():
        os.environ[key] = value
    return merged
