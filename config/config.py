from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, cast


@dataclass(frozen=True)
class Config:
    """SSOT конфіг конектора."""

    ns: str = "fxcm_local"
    profile: str = "local"

    version: str = "0.0.0"
    schema_version: int = 2
    pipeline_version: str = "p0"
    build_version: str = "dev"

    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_password: str = ""
    redis_required: bool = False

    metrics_enabled: bool = True
    metrics_port: int = 9200

    # Параметри та пермикач FXCM
    fxcm_backend: str = "forexconnect"  # disabled | forexconnect
    fxcm_connection: str = "Demo"
    fxcm_host_url: str = "http://www.fxcorporate.com/Hosts.jsp"
    fxcm_username: str = ""
    fxcm_password: str = ""
    fxcm_symbols: List[str] = field(default_factory=lambda: ["XAUUSD"])
    fxcm_poll_interval_ms: int = 500
    fxcm_stale_s: int = 30
    fxcm_resubscribe_retries: int = 1
    fxcm_reconnect_backoff_s: float = 2.0

    history_provider_kind: str = "fxcm_forexconnect"  # fxcm_forexconnect | none

    calendar_tag: str = "fxcm_calendar_v1_ny"
    trading_day_boundary_utc: str = "23:00"
    closed_intervals_utc: List[Tuple[int, int]] = field(default_factory=list)

    max_bars_per_message: int = 512  # макс барів в одному повідомленні OHLCV

    cache_enabled: bool = True  # чи увімкнено файловий кеш OHLCV
    cache_root: str = "cache"  # корінь для файлового кешу
    cache_max_bars: int = 60000  # макс барів в кеші
    cache_warmup_bars: int = 1600  # кількість барів для прогріву кешу при старті
    cache_strict: bool = True  # якщо true, то помилка при кеш-місі для барів не в кеші
    retention_days: int = 7  # кількість днів збереження історії в сховищі
    retention_target_days: int = 7  # SSOT ціль покриття retention для 1m final
    warmup_lookback_days: int = 7  # кількість днів для прогріву при старті
    warmup_default_lookback_days: int = 7  # дефолт прогріву, якщо не задано у команді
    history_chunk_minutes: int = 24  # розмір чанку історії при запиті
    history_chunk_limit: int = 1000  # макс кількість чанків за один запит
    max_requests_per_minute: int = 30  # макс кількість запитів до історії за хвилину
    history_min_sleep_ms: int = 250  # мінімальна пауза між запитами до історії в ms
    tail_guard_window_hours: int = 24  # вікно перевірки tail guard у годинах
    tail_guard_ttl_ms: int = 15 * 60 * 1000  # TTL для збереження стану tail guard у ms
    tail_guard_ttl_minutes: int = 15  # TTL для збереження стану tail guard у хвилинах
    republish_watermark_ttl_minutes: int = 10  # TTL для збереження водяного знаку republish у хвилинах
    tail_guard_default_window_hours: int = 48  # вікно за замовчуванням для tail guard у годинах
    republish_default_window_hours: int = 24  # вікно за замовчуванням для republish у годинах
    tail_guard_checked_ttl_s: int = 300  # TTL для збереження часу останньої перевірки tail guard у секундах
    republish_watermark_ttl_s: int = 300  # TTL для збереження часу останнього водяного знаку republish у секундах
    tail_guard_safe_repair_only_when_market_closed: bool = True  # ремонтувати лише коли ринок закритий
    tail_guard_allow_tfs: List[str] = field(default_factory=lambda: ["1m", "15m", "1h", "4h", "1d"])
    tail_guard_repair_max_gap_minutes: int = 240  # макс розмір розриву для ремонту tail guard у хвилинах
    tail_guard_repair_max_missing_bars: int = 5000  # макс кількість 1m барів для repair
    tail_guard_repair_max_window_ms: int = 24 * 60 * 60 * 1000  # макс діапазон repair у ms
    tail_guard_repair_max_history_chunks: int = 200  # макс чанків history для repair
    republish_tail_window_hours_default: int = 48  # вікно за замовчуванням для republish tail у годинах
    derived_rebuild_default_tfs: List[str] = field(default_factory=lambda: ["5m", "15m", "1h", "4h", "1d"])
    derived_rebuild_window_hours_default: int = 48  # вікно за замовчуванням для rebuild derived у годинах

    commands_enabled: bool = True  # чи увімкнено обробку команд
    commands_channel: str = ""
    status_channel: str = ""
    price_channel: str = ""
    ohlcv_channel: str = ""
    heartbeat_channel: str = ""
    command_bus_heartbeat_period_s: int = 2

    ui_lite_enabled: bool = True  # чи увімкнено UI Lite
    ui_lite_host: str = "127.0.0.1"
    ui_lite_port: int = 8089

    tick_mode: str = "off"
    tick_symbols: List[str] = field(default_factory=lambda: ["XAUUSD"])
    tick_sim_interval_ms: int = 500  # інтервал симуляції тіків у ms
    tick_sim_bid: float = 2000.0
    tick_sim_ask: float = 2000.2

    replay_ticks_path: str = "data/replay_ticks.jsonl"

    preview_mode: str = "off"
    preview_symbol: str = "XAUUSD"
    preview_sim_interval_ms: int = 500  # інтервал симуляції прев'ю у ms

    ohlcv_preview_enabled: bool = True  # чи увімкнено публікацію прев'ю OHLCV
    ohlcv_preview_symbols: List[str] = field(default_factory=lambda: ["XAUUSD"])
    ohlcv_preview_tfs: List[str] = field(default_factory=lambda: ["1m", "5m", "15m", "1h", "4h", "1d"])
    ohlcv_preview_publish_interval_ms: int = 250
    ohlcv_sim_enabled: bool = False  # чи увімкнено симуляцію OHLCV прев'ю

    http_port: int = 8088

    def redis_dsn(self) -> str:
        if self.redis_url:
            return self.redis_url
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    def ch_status(self) -> str:
        if self.status_channel:
            return self.status_channel
        return f"{self.ns}:status"

    def ch_commands(self) -> str:
        if self.commands_channel:
            return self.commands_channel
        return f"{self.ns}:commands"

    def ch_price_tik(self) -> str:
        if self.price_channel:
            return self.price_channel
        return f"{self.ns}:price_tik"

    def ch_ohlcv(self) -> str:
        if self.ohlcv_channel:
            return self.ohlcv_channel
        return f"{self.ns}:ohlcv"

    def key_status_snapshot(self) -> str:
        return f"{self.ns}:status:snapshot"


def _env_overrides_from_env(env: Mapping[str, str]) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    prefix = env.get("FXCM_CHANNEL_PREFIX", "").strip()
    if prefix:
        overrides["ns"] = prefix
    commands_channel = env.get("FXCM_COMMANDS_CHANNEL", "").strip()
    if commands_channel:
        overrides["commands_channel"] = commands_channel
    status_channel = env.get("FXCM_STATUS_CHANNEL", "").strip()
    if status_channel:
        overrides["status_channel"] = status_channel
    price_channel = env.get("FXCM_PRICE_SNAPSHOT_CHANNEL", "").strip()
    if price_channel:
        overrides["price_channel"] = price_channel
    ohlcv_channel = env.get("FXCM_OHLCV_CHANNEL", "").strip()
    if ohlcv_channel:
        overrides["ohlcv_channel"] = ohlcv_channel
    heartbeat_channel = env.get("FXCM_HEARTBEAT_CHANNEL", "").strip()
    if heartbeat_channel:
        overrides["heartbeat_channel"] = heartbeat_channel
    redis_host = env.get("FXCM_REDIS_HOST", "").strip()
    if redis_host:
        overrides["redis_host"] = redis_host
    redis_port = env.get("FXCM_REDIS_PORT", "").strip()
    if redis_port:
        overrides["redis_port"] = int(redis_port)
    redis_password = env.get("FXCM_REDIS_PASSWORD", "").strip()
    if redis_password:
        overrides["redis_password"] = redis_password
    redis_required = env.get("FXCM_REDIS_REQUIRED", "").strip().lower()
    if redis_required in {"1", "true", "yes"}:
        overrides["redis_required"] = True
    if redis_required in {"0", "false", "no"}:
        overrides["redis_required"] = False
    metrics_enabled = env.get("FXCM_METRICS_ENABLED", "").strip().lower()
    if metrics_enabled in {"1", "true", "yes"}:
        overrides["metrics_enabled"] = True
    if metrics_enabled in {"0", "false", "no"}:
        overrides["metrics_enabled"] = False
    metrics_port = env.get("FXCM_METRICS_PORT", "").strip()
    if metrics_port:
        overrides["metrics_port"] = int(metrics_port)
    connection = env.get("FXCM_CONNECTION", "").strip()
    if connection:
        overrides["fxcm_connection"] = connection
    host_url = env.get("FXCM_HOST_URL", "").strip()
    if host_url:
        overrides["fxcm_host_url"] = host_url
    return overrides


def _load_profile_overrides(profile: str) -> Dict[str, Any]:
    if not profile:
        return {}
    module_name = f"config.profile_{profile}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        return {}
    if hasattr(module, "PROFILE_OVERRIDES"):
        profile_overrides = getattr(module, "PROFILE_OVERRIDES")
        if isinstance(profile_overrides, dict):
            return dict(cast(Dict[str, Any], profile_overrides))
    overrides: Dict[str, Any] = {}
    for key in [
        "ns",
        "redis_url",
        "redis_host",
        "redis_port",
        "metrics_port",
        "http_port",
        "ui_lite_host",
        "ui_lite_port",
        "commands_enabled",
    ]:
        if hasattr(module, key):
            overrides[key] = getattr(module, key)
    return overrides


def _profile_from_env_file() -> str:
    env_file = os.environ.get("AI_ONE_ENV_FILE", "").strip()
    if env_file.endswith(".env.local"):
        return "local"
    if env_file.endswith(".env.prod"):
        return "prod"
    return "local"


def load_config(profile: Optional[str] = None) -> Config:
    profile_val = profile or _profile_from_env_file()
    profile_val = str(profile_val)
    base = Config(profile=profile_val)
    env_overrides = _env_overrides_from_env(os.environ)
    overrides = _load_profile_overrides(profile_val)
    if "ns" in overrides and "ns" in env_overrides and overrides["ns"] != env_overrides["ns"]:
        raise ValueError("NS має задаватися одним способом: profile або FXCM_CHANNEL_PREFIX")
    cfg = replace(
        base,
        **env_overrides,
        **overrides,
        fxcm_username=os.environ.get("FXCM_USERNAME", base.fxcm_username),
        fxcm_password=os.environ.get("FXCM_PASSWORD", base.fxcm_password),
    )
    if cfg.redis_required and not cfg.redis_password and not cfg.redis_url:
        raise ValueError("FXCM_REDIS_REQUIRED=true, але redis_password/redis_url не задані")
    if cfg.cache_enabled:
        root = Path(cfg.cache_root)
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".cache_write_probe"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("cache_root не writable") from exc
    return cfg
