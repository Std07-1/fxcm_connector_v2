# REPO_LAYOUT FXCM Connector v2 (annotated)

## High‑level карта
- **app/** — entrypoint та composition root; запускає runtime і піднімає HTTP/UI/metrics. SSOT поведінка старту тут. Див. [app/main.py](../app/main.py) і [app/composition.py](../app/composition.py).
- **config/** — SSOT конфіг, профілі, calendar overrides, шаблони секретів. Ключові runtime перемикачі — тут.
- **core/** — доменна SSOT логіка: контракти/валидація, календар/час, ринкові типи, runtime‑режими.
- **runtime/** — виконання: HTTP API, command bus, tick ingest, preview, FXCM інтеграція, replay, status/metrics, tail_guard.
- **observability/** — метрики/Prometheus.
- **store/** — SQLite сховище, file cache (CSV + meta), schema, derived‑логіка.
- **ui_lite/** — єдина канонічна UI (static + debug endpoint).
- **tests/** — unit/contract/gate тести; fixtures включно з JSONL ticks.
- **tools/** — операційні скрипти та exit gates (runner SSOT).
- **docs/** — SSOT документація/аудити/правила.
- **data/**, **reports/**, **recordings/** — артефакти запусків, аудитів, записані ticks.

## Public boundary (SSOT)
- **core/contracts/public/** — публічні JSON Schema (commands/status/tick/ohlcv). Це єдиний контракт для wire‑payloads.
- **docs/Public API Spec (SSOT).md** — SSOT опис публічних API.
- **docs/Public Surface.md**, **docs/audit_v6_public_surface.md** — межі поверхні доступу.

## Annotated tree (ASCII)

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
|   |-- calendar_overrides.json        # SSOT календарні overrides (NY vs v1 UTC overrides)
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
|   |   |-- calendar.py                 # календар (loader overrides + rails)
|   |   |-- closed_intervals.py         # rails/нормалізація closed_intervals_utc
|   |   |-- sessions.py                 # обчислення сесій
|   |   |-- buckets.py                  # TF buckets
|   |   `-- timestamps.py               # timestamp rails
|   `-- validation/                    # валідатори контрактів
|       `-- validator.py               # schema + rails
|-- data/                              # локальні артефакти/бази/аудити
|   |-- audit_*/                        # audit snapshots та логи
|   |-- file_cache/                    # FileCache (CSV + meta.json)
|   `-- ohlcv_final.sqlite             # локальне SQLite сховище
|-- deploy/                            # інструкції запуску
|   `-- runbook_fxcm_forexconnect.md   # runbook для FXCM
|-- docs/                              # SSOT документація
|   |-- REPO_LAYOUT.md                 # цей файл
|   |-- Public API Spec (SSOT).md      # SSOT API
|   |-- Public Surface.md              # поверхня доступу
|   |-- audit_v6_public_surface.md     # аудит поверхні
|   |-- evidence/                      # архів доказів/вхідних даних
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
|-- store/                             # SQLite storage + FileCache
|   |-- schema.sql                     # SSOT схема БД
|   |-- sqlite_store.py                # доступ до БД
|   |-- live_archive_store.py          # LiveArchive evidence store (append-only)
|   |-- derived_builder.py             # derived OHLCV
|   `-- file_cache/                    # FileCache (CSV + meta.json)
|       |-- cache_utils.py             # SSOT rails/columns/merge+trim
|       `-- history_cache.py           # HistoryCache API
|-- tests/                             # unit/contract/gate тести
|   |-- fixtures/                      # test fixtures (JSON/JSONL)
|   `-- test_*.py                      # тести на rails/контракти
|-- tools/                             # операційні скрипти
|   |-- run_exit_gates.py              # SSOT runner для exit gates
|   |-- run_dev_checks.py              # runner для dev-checks (ruff/mypy/pytest)
|   |-- migrate_v1_calendar_overrides.py # one-off міграція v1 календарних даних
|   |-- validate_tick_fixtures.py      # валідація tick fixtures
|   |-- capture_fxcm_ticks.py          # capture ticks (ops)
|   |-- record_ticks.py                # запис ticks (ops)
|   |-- replay_ticks.py                # thin wrapper → runtime.replay_ticks
|   `-- exit_gates/                    # manifests + gate modules
|       |-- manifest.json              # дефолтний manifest (містить календарні гейти)
|       |-- manifest_p1_calendar.json  # календарні гейти (точковий запуск)
|       |-- manifest*.json             # інші набори gate'ів
|       `-- gates/                     # окремі gate'и
|           |-- gate_tick_event_time_not_wallclock.py # rail: tick_ts_ms не з wall-clock
|           |-- gate_tick_skew_non_negative.py  # rail: tick_skew_ms >= 0
|           |-- gate_calendar_schedule_drift.py # rail: schedule drift (daily break + weekly boundary)
|           |-- gate_calendar_closed_intervals.py # rail: валідація closed_intervals_utc
|           |-- gate_live_archive_sqlite.py # rail: live_archive sqlite
|           |-- gate_file_cache_schema.py # rail: file cache schema/semantics
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
`-- README.md                          # короткий README
```

## Файли налаштувань/оркестрації
- **config/** — SSOT конфіг: [config/config.py](../config/config.py), [config/calendar_overrides.json](../config/calendar_overrides.json).
- **requirements*.txt** — залежності: [requirements.txt](../requirements.txt), [requirements-dev.txt](../requirements-dev.txt).
- **.env.example** — відсутній (є .env/.env.local/.env.prod; не містити секрети в доках).
- **Docker/Docker Compose** — не знайдено.
- **systemd/nginx/deploy** — [deploy/runbook_fxcm_forexconnect.md](../deploy/runbook_fxcm_forexconnect.md); systemd/nginx файли не знайдено.
- **CI** — workflows не знайдено; є [.github/copilot-instructions.md](../.github/copilot-instructions.md).
