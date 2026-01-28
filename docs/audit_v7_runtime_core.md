# Audit v7 — runtime/core (стабільність, архітектура, інженерія)

Дата: 2026-01-27
Фокус: runtime, core. Мета — оцінити стабільність, якість коду/архітектури, інженерні ризики.

---

## 1) Архітектура (узагальнення)

### 1.1 Базовий ланцюжок даних
- **Tick ingest → Preview OHLCV → UI Lite**: FXCM stream → нормалізація tick → preview builder (SSOT у core) → Redis {NS}:ohlcv → UI Lite.
- **Final SSOT → Derived HTF**: 1m final у SQLite → derived HTF (history_agg) → publish final.
- **Контракти**: публічна поверхня визначена JSON Schema (allowlist + fail‑fast).

### 1.2 Розділення відповідальностей
- **core/** — домен/контракти/календар/rails.
- **runtime/** — реалізація пайплайнів, I/O, команд, статус/метрики.
- **store/** — SSOT SQLite.
- **ui_lite/** — read‑only UI + валідатори inbound payload.

### 1.3 Рейкові інваріанти
- Відсутність silent‑fallback.
- Rail‑перевірки часу (ms, upper bound), канонічні OHLCV ключі.
- SSOT preview builder у core; runtime — thin wrapper.

---

## 2) Стабільність (runtime/core)

### 2.1 Позитивні сигнали
- **FXCM FSM**: FSM/state‑machine з backoff/paused_market_closed.
- **TailGuard**: є явний `ssot_empty` guard, marks, near/far tiers.
- **Rails**: вимоги часу/контрактів централізовані в core/validation і core/time.

### 2.2 Потенційні вузькі місця
- **FXCM event time**: залежить від наявності `event_ts` у FXCM offers.
- **Store empty**: більшість final/derived процесів залежні від наповненого 1m.
- **Preview/Final gap**: preview не персиститься; final залежить від history provider.

---

## 3) Дефекти/аномалії (поточний стан)

- **No critical defects** за підсумком останніх повних перевірок (ruff/mypy/pytest/exit gates — OK).
- **Operational**: якщо FXCM history provider не дає bars — warmup/backfill фактично порожні.
- **UI Lite**: inbound валідатор може відкидати payload при неправильних top‑level полях (виправлено — візуалізація OK).

---

## 4) Технічний борг

- **Calendar closed_intervals_utc**: зараз порожні; якщо потрібна точна відповідність v1 — необхідне заповнення даних (не логіки).
- **Calendar overrides з v1 (корисні правила)**:
 	- v1 використовував UTC‑оверрайди (daily break 22:00–23:01 UTC, weekly open 23:01 UTC, weekly close 21:45 UTC) та explicit closed_intervals_utc.
 	- v1 мав список FXCM holidays (UTC дати) як SSOT дані, що впливають на `is_trading_time`.
 	- v1 задавав 1d boundary як anchor від daily break (DST‑aware), та відкидав неповні HTF bucket.
- **History readiness**: залежність від FXCM SDK/secrets та readiness/backoff конфігів.
- **Operational tooling**: частина audit‑скриптів залежить від локального оточення (PowerShell/Redis).

---

## 5) Дублювання та роз'їзд

- **Preview SSOT**: усунуто дублювання — core/market/preview_builder є SSOT, runtime thin wrapper.
- **Exit gates**: SSOT runner єдиний (tools/run_exit_gates.py), legacy wrappers — thin.
- **Роз'їзд** можливий лише у даних (fixtures/overrides), не у коді. Потрібна дисципліна оновлення fixtures.

---

## 6) Рейки (rails)

- **Час**: `MIN_EPOCH_MS`, `MAX_EPOCH_MS` + `_require_ms_int`.
- **Contract‑first**: strict allowlist у JSON Schema; invalid → ContractError.
- **NoMix**: rails на змішування потоків final/preview.
- **TailGuard**: `ssot_empty` guard, marks persistence, budget rails.

---

## 7) Гейти (exit gates)

- Набір гейтів охоплює: runtime rails, preview bounds, tick units, tail_guard, history rails, UI gap scans.
- Повний набір проходить у .venv (перевірено у поточному циклі).

---

## 8) Ризики

1) **FXCM history 0 bars** → warmup/backfill не наповнюють 1m store.
2) **Data drift через environment** → без стабільного профілю секретів/SDK може бути часткова працездатність.
3) **Calendar data gap** → closed_intervals_utc порожні (ризик розбіжності з прод‑календарем).
4) **Calendar schedule drift** → v1 UTC‑оверрайди не перенесені; ризик різних weekly open/close і daily break у проді.

---

## 9) Рекомендації (пріоритет)

1) **History provider**: підтвердити реальний потік історії (параметри FXCM) або зафіксувати ліміт/режим деградації.
2) **Calendar data**: наповнити closed_intervals_utc SSOT даними (без зміни логіки).
2.1) **Calendar schedule**: узгодити, чи переносимо v1 UTC‑оверрайди (weekly open/close, daily break) у профілі, або залишаємо NY‑локальні правила. Рішення має бути як дані в config/calendar_overrides.json.
3) **Warmup/backfill SOP**: додати runbook для обов’язкового 1m seed перед derived rebuild.
4) **Fixtures discipline**: автоматичний sanity‑check fixtures у bootstrap (перед pytest).
5) **Observability**: додати короткий health‑summary для history readiness та store coverage.

---

## 10) Висновок

- **Архітектура стабільна**, SSOT/rails/гейти на місці.
- **Критичні дефекти не виявлені**; головні ризики — операційні (дані/історія/календарні дані).
- **Наступний крок** — вирішити data‑ризики (history + calendar data), без зміни core/runtime логіки.
