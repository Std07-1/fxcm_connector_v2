# FXCM Connector vNext

## Короткий опис

FXCM Connector vNext — конектор для FXCM із реальним стрімом через ForexConnect, побудовою preview OHLCV у realtime, зберіганням final 1m у SQLite та статусним API/моніторингом. Орієнтований на Python 3.7, суворі контракти (JSON Schema) і fail‑fast валідацію. REST/fxcmpy не використовується.

## Ключові можливості

- **Live preview OHLCV** (1m + HTF) з жорсткими рейками часу/сортування/дедуп.
- **SSOT final 1m** у SQLite з інваріантами та derived HTF (history_agg).
- **Строгі контракти** для tick/ohlcv/status/commands (allowlist, fail‑fast).
- **UI Lite** як канонічна UI (HTTP + WS + /debug, health/STALE/overlay).
- **Exit gates** як SSOT контроль якості (tools/run_exit_gates.py).

## Public Surface (SSOT)

### Redis
- **Snapshot**: {NS}:status:snapshot (JSON, валідний status_v2).
- **Pub/Sub**: {NS}:status, {NS}:ohlcv, {NS}:price_tik.
- **Commands**: {NS}:commands (commands_v1).

### HTTP
- **/api/status** — читає status snapshot.
- **/api/ohlcv** — preview з in‑memory cache, final зі SQLite.
- **/chart** — redirect на UI Lite або 503, якщо UI Lite вимкнено.

### UI Lite
- **/** — UI.
- **/debug** — стан UI Lite (rx/tx/last payload, errors).
- **WS** — snapshot/bar payload (type=snapshot|bar).

## Архітектура та SSOT

- **SSOT контракти**: core/contracts/public/*.json.
- **SSOT preview builder**: core/market/preview_builder.py (runtime — thin wrapper).
- **SSOT storage**: store/sqlite_store.py + store/schema.sql.
- **Режими runtime**: FOREXCONNECT / REPLAY / DISABLED (SIM заборонено).
- **Без silent fallback**: помилки → errors[]/degraded[] або hard fail.

## Вимоги та середовище

- Python 3.7.
- ForexConnect SDK (DLL у PATH).
- Redis.
- .env використовується лише як перемикач профілю (AI_ONE_ENV_FILE).
- Секрети тільки у .env.local/.env.prod (логін/пароль FXCM, токени).

## Швидкий старт (local)

1) Встановити Python 3.7 та ForexConnect SDK.
2) Налаштувати .env → тільки AI_ONE_ENV_FILE, секрети в .env.local/.env.prod.
3) Запуск:

```
C:/Aione_projects/fxcm_connector_v2/.venv/Scripts/python.exe -m app.main
```

## Демо‑чеклист

- FXCM state == streaming.
- tick_total > 0.
- ohlcv_preview.preview_total > 0.
- UI Lite не має ohlcv_contract_error.

## UI Lite manual checks

- redis-cli PUBSUB NUMSUB "${NS}:ohlcv" -> >= 1
- Invoke-WebRequest http://127.0.0.1:8089/debug
- WS subscribe: відкрити UI, натиснути Subscribe, перевірити snapshot/bar в консолі браузера
- /debug: last_payload_ts_ms > 0, last_payload_open_time_ms > 0, last_payload_mode == preview|final, last_ui_bar_time_s > 0

## Exit Gates (SSOT)

- Канонічний runner: tools/run_exit_gates.py.
- Маніфести: tools/exit_gates/manifest*.json (P0/P1/P2/повний).
- Bootstrap P0: tools/bootstrap_p0.ps1 (ruff/mypy/pytest + P0 gates).

## Конфіг

- config/config.py — SSOT для каналів/портів/таймфреймів/rails.
- config/calendar_overrides.json — SSOT календар (NY recurrence + профілі, XAU 23:00 UTC).
- docs/Public API Spec (SSOT).md — нормативні правила Public API.

## Поточна карта REPO_LAYOUT (актуальна)

Нижче — поточна карта (повна версія синхронізована з docs/REPO_LAYOUT.md).

### High‑level карта
- **app/** — entrypoint та composition root; запускає runtime і піднімає HTTP/UI/metrics.
- **config/** — SSOT конфіг, профілі, calendar overrides, шаблони секретів.
- **core/** — доменна SSOT логіка: контракти/валидація, календар/час, ринкові типи, runtime‑режими.
- **runtime/** — виконання: HTTP API, command bus, tick ingest, preview, FXCM інтеграція, replay, status/metrics, tail_guard.
- **observability/** — метрики/Prometheus.
- **store/** — SQLite сховище, schema, derived‑логіка.
- **ui_lite/** — єдина канонічна UI (static + debug endpoint).
- **tests/** — unit/contract/gate тести; fixtures включно з JSONL ticks.
- **tools/** — операційні скрипти та exit gates (runner SSOT).
- **docs/** — SSOT документація/аудити/правила.
- **data/**, **reports/**, **recordings/** — артефакти запусків, аудитів, записані ticks.

### Annotated tree (ASCII)

```
.                                    # корінь репозиторію
|-- .github/                          # інструкції Copilot
|   `-- copilot-instructions.md       # правила роботи
|-- .vscode/                           # workspace конфіг VS Code
|-- app/                               # entrypoint + composition root
|   |-- main.py                        # запуск runtime (entrypoint)
|   `-- composition.py                 # складання всіх компонентів runtime
|-- config/                            # SSOT конфіг
|   |-- config.py                      # основний конфіг та канали (history_provider_kind)
|   |-- calendar_overrides.json        # SSOT календар (NY recurrence + profiles, XAU 23:00 UTC)
|   |-- profile_template.py            # шаблон профілю
|   `-- secrets_template.py            # шаблон секретів
|-- core/                              # доменна SSOT логіка
|   |-- env_loader.py                  # завантаження env + allowlist
|   |-- fixtures_path.py               # SSOT шляхи до fixtures
|   |-- contracts/public/              # SSOT JSON schemas (public boundary)
|   |   |-- commands_v1.json            # контракт команд
|   |   |-- status_v2.json              # контракт status
|   |   |-- tick_v1.json                # контракт tick
|   |   `-- ohlcv_v1.json               # контракт ohlcv
|   |-- market/                        # ринкові типи/правила
|   |   |-- tick.py                     # нормалізація tick (SSOT інваріанти)
|   |   |-- preview_1m_builder.py       # 1m preview builder (tick -> bar)
|   |   |-- preview_builder.py          # SSOT preview builder (multi‑TF, 1d boundary через buckets.get_bucket_open_ms)
|   |   `-- replay_policy.py            # replay policy (schema + closed + monotonic)
|   |-- runtime/                       # SSOT режим backend
|   |   `-- mode.py                     # режими FOREXCONNECT/REPLAY/DISABLED
|   |-- time/                          # SSOT час/календар
|   |   |-- calendar.py                 # календар (NY recurrence + UTC overrides)
|   |   |-- sessions.py                 # обчислення сесій
|   |   |-- buckets.py                  # TF buckets
|   |   `-- timestamps.py               # timestamp rails
|   `-- validation/                    # валідатори контрактів
|       `-- validator.py               # schema + rails
|-- data/                              # локальні артефакти/бази/аудити
|   |-- audit_*/                        # audit snapshots та логи
|   `-- ohlcv_final.sqlite             # локальне SQLite сховище
|-- deploy/                            # інструкції запуску
|   `-- runbook_fxcm_forexconnect.md   # runbook для FXCM
|-- docs/                              # SSOT документація
|   |-- REPO_LAYOUT.md                 # цей файл
|   |-- Public API Spec (SSOT).md      # SSOT API
|   |-- Public Surface.md              # поверхня доступу
|   |-- audit_v6_public_surface.md     # аудит поверхні
|   `-- ...                            # решта аудитів/специфікацій
|-- fxcm/                              # FXCM історичні провайдери/стаби
|   `-- history_fxcm_provider.py       # скелет провайдера FXCM історії
|-- observability/                     # метрики
|   `-- metrics.py                     # Prometheus метрики (tick skew/drop)
|-- recordings/                        # збережені записи ticks
|   `-- ticks/                         # каталоги записаних ticks
|-- reports/                           # результати gate/audit
|   `-- exit_gates/                    # результати exit gates
|-- runtime/                           # runtime виконання
|   |-- http_server.py                 # HTTP API (/api/*, /chart stub)
|   |-- status.py                      # status snapshot + tick event/snap/skew + coverage telemetry + market.tz_backend
|   |-- command_bus.py                 # обробка команд
|   |-- tick_feed.py                   # публікація tick
|   |-- replay_ticks.py                # replay ingest (REAL‑only)
|   |-- fxcm_forexconnect.py           # FXCM інтеграція (tick_ts=event_ts, snap_ts=receipt_ts)
|   |-- handlers_p3.py                 # командні handler'и P3
|   |-- handlers_p4.py                 # handler'и P4
|   |-- ohlcv_preview.py               # preview обгортка
|   |-- preview_builder.py             # thin wrapper над core preview builder
|   |-- tail_guard.py                  # tail_guard логіка (near/far tiers + marks + repair)
|   |-- republish.py                   # republish логіка
|   |-- rebuild_derived.py             # rebuild derived
|   |-- backfill.py                    # backfill логіка
|   |-- warmup.py                      # warmup логіка
|   |-- no_mix.py                      # rails на мікс потоків
|   |-- history_provider.py            # Protocol для history provider + readiness/backoff rail
|   |-- history_sim_provider.py        # runtime sim заборонено (rail)
|   |-- tick_sim*.py                   # runtime sim заборонено (rail)
|   |-- ohlcv_sim*.py                  # runtime sim заборонено (rail)
|   |-- static/                        # legacy static; /chart більше не читає ці файли
|   `-- fxcm/                          # FXCM runtime модулі (adapter/fsm/session/history_budget)
|-- store/                             # SQLite storage
|   |-- schema.sql                     # SSOT схема БД
|   |-- sqlite_store.py                # доступ до БД
|   `-- derived_builder.py             # derived OHLCV
|-- tests/                             # unit/contract/gate тести
|   |-- fixtures/                      # test fixtures (JSON/JSONL)
|   `-- test_*.py                      # тести на rails/контракти
|-- tools/                             # операційні скрипти
|   |-- run_exit_gates.py              # SSOT runner для exit gates
|   |-- validate_tick_fixtures.py      # валідація tick fixtures
|   |-- capture_fxcm_ticks.py          # capture ticks (ops)
|   |-- record_ticks.py                # запис ticks (ops)
|   |-- replay_ticks.py                # thin wrapper → runtime.replay_ticks
|   `-- exit_gates/                    # manifests + gate modules
|       |-- manifest*.json             # набори gate'ів
|       `-- gates/                     # окремі gate'и
|           |-- gate_tick_event_time_not_wallclock.py # rail: tick_ts_ms не з wall-clock
|           |-- gate_tick_skew_non_negative.py  # rail: tick_skew_ms >= 0
|-- ui_lite/                           # канонічна UI. “oscilloscope” для конектора
|   |-- server.py                      # UI Lite HTTP + /debug + inbound OHLCV/status validation + health WS (N/A/STALE)
|   `-- static/                        # UI Lite static assets
|-- Work/                              # робочий журнал (SSOT)
|   `-- 01log.md                       # append‑only work log
|-- requirements.txt                   # прод‑залежності
|-- requirements-dev.txt               # dev‑залежності
|-- pytest.ini                         # pytest конфіг
|-- mypy.ini                           # mypy конфіг
|-- ruff.toml                          # ruff конфіг
|-- mcp_config.json                    # MCP конфіг
|-- .env / .env.local / .env.prod      # env файли (секрети)
|-- .gitignore                         # git ignore
`-- README.md                          # цей README
```

## Додаткові посилання

- docs/REPO_LAYOUT.md — повна мапа та пояснення.
- docs/Public API Spec (SSOT).md — контрактні правила.
- docs/exit_gates.md — як запускати gates через runner.
