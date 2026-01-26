#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PY_BIN="${PY_BIN:-python3.7}"

if ! command -v "$PY_BIN" >/dev/null 2>&1; then
    echo "ERROR: python3.7 не знайдено. Вкажи PY_BIN=/path/to/python3.7" >&2
    exit 2
fi

"$PY_BIN" -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,7) else 2)' || {
    echo "ERROR: потрібен Python 3.7 (запусти через .venv)" >&2
    exit 2
}

if [ ! -d ".venv" ]; then
    "$PY_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt

ruff check .
mypy .
pytest -q
python tools/run_exit_gates.py --out reports/exit_gates --manifest tools/exit_gates/manifest.json
echo "OK: P0 bootstrap завершено"
exit 0

mkdir -p app config core/contracts/public core/time core/validation runtime observability docs .vscode tools

touch app/__init__.py config/__init__.py core/__init__.py core/time/__init__.py core/validation/__init__.py runtime/__init__.py observability/__init__.py

cat > .gitignore <<'EOF'
.venv/
__pycache__/
*.pyc
.pytest_cache/
*.log
.DS_Store
EOF

cat > .vscode/settings.json <<'EOF'
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.analysis.typeCheckingMode": "basic",
  "python.testing.pytestEnabled": false
}
EOF

cat > pyproject.toml <<'EOF'
[project]
name = "fxcm-connector-vnext"
version = "0.0.0"
requires-python = ">=3.10"
dependencies = [
  "redis>=5.0.0",
  "prometheus_client>=0.20.0",
  "jsonschema>=4.22.0"
]
EOF

cat > core/contracts/public/commands_v1.json <<'EOF'
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "commands_v1.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["cmd", "req_id", "ts", "args"],
  "properties": {
    "cmd": { "type": "string", "minLength": 1 },
    "req_id": { "type": "string", "minLength": 1 },
    "ts": { "type": "integer", "minimum": 1000000000000 },
    "args": { "type": "object", "additionalProperties": true }
  }
}
EOF

cat > core/contracts/public/status_v2.json <<'EOF'
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "status_v2.json",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "ts",
    "build_version",
    "pipeline_version",
    "schema_version",
    "process",
    "market",
    "errors",
    "degraded",
    "last_command"
  ],
  "properties": {
    "ts": { "type": "integer", "minimum": 1000000000000 },
    "build_version": { "type": "string", "minLength": 1 },
    "pipeline_version": { "type": "string", "minLength": 1 },
    "schema_version": { "type": "integer", "minimum": 1 },

    "process": {
      "type": "object",
      "additionalProperties": false,
      "required": ["pid", "uptime_s", "state"],
      "properties": {
        "pid": { "type": "integer", "minimum": 1 },
        "uptime_s": { "type": "number", "minimum": 0 },
        "state": { "type": "string", "enum": ["starting", "running", "degraded", "error", "stopped"] }
      }
    },

    "market": {
      "type": "object",
      "additionalProperties": false,
      "required": ["is_open", "next_open_utc", "next_pause_utc", "calendar_tag"],
      "properties": {
        "is_open": { "type": "boolean" },
        "next_open_utc": { "type": "string" },
        "next_pause_utc": { "type": "string" },
        "calendar_tag": { "type": "string", "minLength": 1 }
      }
    },

    "errors": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["code", "severity", "message", "ts"],
        "properties": {
          "code": { "type": "string", "minLength": 1 },
          "severity": { "type": "string", "enum": ["info", "warn", "error", "critical"] },
          "message": { "type": "string", "minLength": 1 },
          "ts": { "type": "integer", "minimum": 1000000000000 },
          "symbol": { "type": "string" },
          "tf": { "type": "string" },
          "context": { "type": "object", "additionalProperties": true }
        }
      }
    },

    "degraded": { "type": "array", "items": { "type": "string", "minLength": 1 } },

    "last_command": {
      "type": "object",
      "additionalProperties": false,
      "required": ["cmd", "req_id", "state", "started_ts"],
      "properties": {
        "cmd": { "type": "string", "minLength": 1 },
        "req_id": { "type": "string", "minLength": 1 },
        "state": { "type": "string", "enum": ["running", "ok", "error"] },
        "started_ts": { "type": "integer", "minimum": 1000000000000 },
        "finished_ts": { "type": "integer", "minimum": 1000000000000 },
        "result": { "type": "object", "additionalProperties": true }
      }
    }
  }
}
EOF

cat > config/config.py <<'EOF'
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass(frozen=True)
class Config:
    """SSOT конфіг конектора. Без feature flags в ENV."""
    ns: str = "fxcm_local"
    redis_url: str = "redis://127.0.0.1:6379/0"
    metrics_port: int = 9200

    trading_day_boundary_utc: str = "22:00"
    calendar_tag: str = "stub_calendar_v0"
    closed_intervals_utc: List[Tuple[int, int]] = field(default_factory=list)

    max_bars_per_message: int = 1024

    build_version: str = "dev"
    pipeline_version: str = "p0"
    schema_version: int = 2

    def ch_status(self) -> str:
        return f"{self.ns}:status"

    def ch_commands(self) -> str:
        return f"{self.ns}:commands"

    def key_status_snapshot(self) -> str:
        return f"{self.ns}:status:snapshot"
EOF

cat > core/validation/validator.py <<'EOF'
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from jsonschema import Draft202012Validator


class ContractError(ValueError):
    """Помилка контракту payload: порушено інваріант або schema."""


@dataclass(frozen=True)
class SchemaValidator:
    """Валідатор JSON payload за allowlist schema (additionalProperties:false)."""
    root_dir: Path

    def _load_schema(self, rel_path: str) -> Dict[str, Any]:
        p = self.root_dir / rel_path
        if not p.exists():
            raise ContractError(f"Schema не знайдено: {p}")
        return json.loads(p.read_text(encoding="utf-8"))

    def validate(self, rel_schema_path: str, payload: Dict[str, Any]) -> None:
        schema = self._load_schema(rel_schema_path)
        v = Draft202012Validator(schema)
        errors = sorted(v.iter_errors(payload), key=lambda e: e.path)
        if errors:
            e0 = errors[0]
            raise ContractError(f"Порушено schema {rel_schema_path}: {e0.message}")
EOF

cat > core/time/calendar.py <<'EOF'
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Tuple


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MarketClock:
    """Stub календар. Поки що визначає відкритість лише через closed_intervals_utc."""
    calendar_tag: str
    closed_intervals_utc: List[Tuple[int, int]]

    def is_open(self, now_ms: int) -> bool:
        for s, e in self.closed_intervals_utc:
            if s <= now_ms < e:
                return False
        return True

    def next_open_utc(self) -> str:
        return ""

    def next_pause_utc(self) -> str:
        return ""
EOF

cat > runtime/publisher.py <<'EOF'
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict

import redis


def dumps_canonical(obj: Dict[str, Any]) -> str:
    """Канонічна JSON-серіалізація для дроту."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


@dataclass
class RedisPublisher:
    """Єдина точка запису в Redis для status/snapshot."""
    client: redis.Redis

    def set_snapshot(self, key: str, payload: Dict[str, Any]) -> None:
        self.client.set(key, dumps_canonical(payload))

    def publish(self, channel: str, payload: Dict[str, Any]) -> None:
        self.client.publish(channel, dumps_canonical(payload))
EOF

cat > runtime/status.py <<'EOF'
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.time.calendar import MarketClock
from core.validation.validator import ContractError, SchemaValidator
from runtime.publisher import RedisPublisher


@dataclass
class StatusState:
    """Поточний стан для побудови snapshot."""
    started_monotonic: float = field(default_factory=time.monotonic)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    degraded: List[str] = field(default_factory=list)
    last_command: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StatusManager:
    """Генерує та публікує status snapshot як SSOT для ops/UI."""
    publisher: RedisPublisher
    schema_validator: SchemaValidator
    schema_path: str
    clock: MarketClock
    build_version: str
    pipeline_version: str
    schema_version: int
    snapshot_key: str
    status_channel: str
    pid: int

    state: StatusState = field(default_factory=StatusState)

    def uptime_s(self) -> float:
        return max(0.0, time.monotonic() - self.state.started_monotonic)

    def add_error(self, code: str, severity: str, message: str, ts_ms: int, context: Optional[Dict[str, Any]] = None) -> None:
        e: Dict[str, Any] = {"code": code, "severity": severity, "message": message, "ts": ts_ms}
        if context:
            e["context"] = context
        self.state.errors.append(e)

    def set_last_command(self, cmd: str, req_id: str, state: str, started_ts: int, finished_ts: Optional[int] = None, result: Optional[Dict[str, Any]] = None) -> None:
        lc: Dict[str, Any] = {"cmd": cmd, "req_id": req_id, "state": state, "started_ts": started_ts}
        if finished_ts is not None:
            lc["finished_ts"] = finished_ts
        if result is not None:
            lc["result"] = result
        self.state.last_command = lc

    def build_snapshot(self, now_ms: int) -> Dict[str, Any]:
        snap = {
            "ts": now_ms,
            "build_version": self.build_version,
            "pipeline_version": self.pipeline_version,
            "schema_version": self.schema_version,
            "process": {"pid": self.pid, "uptime_s": self.uptime_s(), "state": "running"},
            "market": {
                "is_open": self.clock.is_open(now_ms),
                "next_open_utc": self.clock.next_open_utc(),
                "next_pause_utc": self.clock.next_pause_utc(),
                "calendar_tag": self.clock.calendar_tag
            },
            "errors": list(self.state.errors),
            "degraded": list(self.state.degraded),
            "last_command": dict(self.state.last_command) if self.state.last_command else {
                "cmd": "bootstrap",
                "req_id": "bootstrap",
                "state": "ok",
                "started_ts": now_ms
            }
        }
        return snap

    def publish(self, now_ms: int) -> Dict[str, Any]:
        snap = self.build_snapshot(now_ms)
        try:
            self.schema_validator.validate(self.schema_path, snap)
        except ContractError as e:
            # Loud: навіть status має бути валідним; якщо ні — фіксуємо помилку і пробуємо ще раз.
            self.add_error("status_schema_invalid", "critical", str(e), now_ms)
            snap = self.build_snapshot(now_ms)
            self.schema_validator.validate(self.schema_path, snap)

        self.publisher.set_snapshot(self.snapshot_key, snap)
        self.publisher.publish(self.status_channel, snap)
        return snap
EOF

cat > runtime/command_bus.py <<'EOF'
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set

from core.validation.validator import ContractError, SchemaValidator
from runtime.status import StatusManager


@dataclass
class CommandBus:
    """Слухає Pub/Sub канал команд і оновлює status snapshot (ACK через status)."""
    schema_validator: SchemaValidator
    schema_path: str
    status: StatusManager
    commands_channel: str
    known_but_not_implemented: Set[str]

    def handle_raw(self, raw: str, now_ms: int) -> None:
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ContractError("Команда має бути JSON object")
            self.schema_validator.validate(self.schema_path, payload)
        except (json.JSONDecodeError, ContractError) as e:
            self.status.add_error("command_invalid", "error", str(e), now_ms)
            self.status.set_last_command("invalid", "invalid", "error", now_ms, now_ms)
            return

        cmd = payload["cmd"]
        req_id = payload["req_id"]

        self.status.set_last_command(cmd, req_id, "running", now_ms)

        if cmd in self.known_but_not_implemented:
            self.status.add_error("not_implemented", "error", f"Команда {cmd} ще не реалізована у P0", now_ms, {"cmd": cmd})
            self.status.set_last_command(cmd, req_id, "error", now_ms, now_ms, {"reason": "not_implemented"})
            return

        self.status.add_error("unknown_command", "error", f"Невідома команда {cmd}", now_ms, {"cmd": cmd})
        self.status.set_last_command(cmd, req_id, "error", now_ms, now_ms, {"reason": "unknown_command"})
EOF

cat > observability/metrics.py <<'EOF'
from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import Counter, Gauge, start_http_server


@dataclass
class Metrics:
    """Набір базових метрик конектора."""
    heartbeat_ts: Gauge
    status_publishes_total: Counter
    commands_total: Counter
    errors_total: Counter


def start_metrics_server(port: int) -> Metrics:
    """Піднімає /metrics і повертає метрики."""
    start_http_server(port)
    heartbeat_ts = Gauge("connector_heartbeat_ts", "Останній heartbeat (epoch ms)")
    status_publishes_total = Counter("connector_status_publishes_total", "Кількість публікацій status")
    commands_total = Counter("connector_commands_total", "Кількість команд", ["cmd", "state"])
    errors_total = Counter("connector_errors_total", "Кількість помилок", ["code", "severity"])
    return Metrics(
        heartbeat_ts=heartbeat_ts,
        status_publishes_total=status_publishes_total,
        commands_total=commands_total,
        errors_total=errors_total
    )
EOF

cat > app/main.py <<'EOF'
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import redis

from config.config import Config
from core.time.calendar import MarketClock
from core.validation.validator import SchemaValidator
from observability.metrics import start_metrics_server
from runtime.command_bus import CommandBus
from runtime.publisher import RedisPublisher
from runtime.status import StatusManager


def _now_ms() -> int:
    return int(time.time() * 1000)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S"
    )


def main() -> None:
    _setup_logging()
    log = logging.getLogger("connector")

    cfg = Config()
    log.info("Старт конектора P0. NS=%s redis_url=%s", cfg.ns, cfg.redis_url)

    root_dir = Path(__file__).resolve().parents[1]
    validator = SchemaValidator(root_dir=root_dir)

    r = redis.Redis.from_url(cfg.redis_url, decode_responses=True)
    publisher = RedisPublisher(client=r)

    metrics = start_metrics_server(cfg.metrics_port)
    log.info("Prometheus /metrics піднято на порту %s", cfg.metrics_port)

    clock = MarketClock(calendar_tag=cfg.calendar_tag, closed_intervals_utc=cfg.closed_intervals_utc)

    status = StatusManager(
        publisher=publisher,
        schema_validator=validator,
        schema_path="core/contracts/public/status_v2.json",
        clock=clock,
        build_version=cfg.build_version,
        pipeline_version=cfg.pipeline_version,
        schema_version=cfg.schema_version,
        snapshot_key=cfg.key_status_snapshot(),
        status_channel=cfg.ch_status(),
        pid=os.getpid()
    )
    # Loud: календар поки stub
    status.state.degraded.append("calendar_stub")

    known = {"fxcm_warmup", "fxcm_backfill", "fxcm_tail_guard", "fxcm_republish_tail"}
    bus = CommandBus(
        schema_validator=validator,
        schema_path="core/contracts/public/commands_v1.json",
        status=status,
        commands_channel=cfg.ch_commands(),
        known_but_not_implemented=known
    )

    pubsub = r.pubsub()
    pubsub.subscribe(cfg.ch_commands())
    log.info("Підписка на команди: %s", cfg.ch_commands())

    # Initial publish
    now_ms = _now_ms()
    status.set_last_command("bootstrap", "bootstrap", "ok", now_ms, now_ms, {"note": "P0 started"})
    status.publish(now_ms)
    metrics.status_publishes_total.inc()

    last_status_publish = time.monotonic()

    while True:
        now_ms = _now_ms()
        metrics.heartbeat_ts.set(now_ms)

        msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if msg and msg.get("type") == "message":
            raw = msg.get("data")
            if isinstance(raw, str):
                bus.handle_raw(raw, now_ms)
                # Метрики по last_command
                lc = status.state.last_command
                metrics.commands_total.labels(cmd=lc.get("cmd", "unknown"), state=lc.get("state", "unknown")).inc()
                if status.state.errors:
                    e = status.state.errors[-1]
                    metrics.errors_total.labels(code=e["code"], severity=e["severity"]).inc()

                status.publish(now_ms)
                metrics.status_publishes_total.inc()

        # Публікуємо status раз на ~5с навіть без команд (щоб snapshot не “застиг”)
        if (time.monotonic() - last_status_publish) >= 5.0:
            status.publish(now_ms)
            metrics.status_publishes_total.inc()
            last_status_publish = time.monotonic()


if __name__ == "__main__":
    main()
EOF

cat > README.md <<'EOF'
# FXCM Connector vNext — P0

P0 = skeleton: status/commands/validator/metrics. Без FXCM, без store, без OHLCV/Tick даних.

## Швидкий старт (Linux)

### 1) Python venv
```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
