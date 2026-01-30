Актуальний перелік P‑slice‑ів для проєкту Connector v2, сформований у стилі **PRE (MODE=PATCH)**.

---

## Фаза 0 — завершити “гейти як дисципліну”

### P1.3 – Exit Gates: manifest‑by‑default + docs + rail проти direct‑run**

* **Мета:** Нові гейти (schedule drift, closed intervals) мають запускатися разом з існуючими через дефолтний `manifest`. Заборонити прямий запуск `gate_*.py` — єдиний спосіб виклику через `runner`.
* **Scope:** `tools/exit_gates/manifest.json`, `tools/run_exit_gates.py`, `tools/exit_gates/gates/*`, `docs/REPO_LAYOUT.md`, `tests/*`.
* **Non‑goals:** зміни календарних правил, FXCM інтеграція, історія, UI.
* **Інваріанти/рейки:**

  * Мінімальний диф — лише те, що необхідно для manifest.
  * Runner (`python -m tools.run_exit_gates`) є SSOT запуску.
  * Прямий запуск `gate_*.py` → жорсткий fail з поясненням.
* **Acceptance Criteria:**

  * `python -m tools.run_exit_gates` піднімає всі гейти з manifest одним запуском.
  * `python tools/exit_gates/gates/gate_*.py` → FAIL (rail enforced).
  * `docs/REPO_LAYOUT.md` відображає нові артефакти та manifest.
* **Proof‑pack:**

  * `data/audit_vX/exit_gates_manifest_run.txt` — лог спільного запуску.
  * `data/audit_vX/direct_run_blocked.txt` — приклад відмови прямого запуску.

---

## Фаза 1 — прибрати stub‑календар і зробити календар прод‑придатним

### P7 – Calendar SSOT: real schedule + closed intervals + drift‑gates**

* **Мета:** Замінити stub‑календар реальним календарем:

  * Коректні `is_open`, `next_open_utc`, `next_pause_utc`.
  * `closed_intervals` беруться з SSOT (JSON).
  * Додати гейти: `schedule_drift` та `closed_intervals` validity.
* **Scope:** `core/time/calendar.py`, `config/calendar_overrides.json` (або інше SSOT), `tools/exit_gates/gate_schedule_drift.py`, `tools/exit_gates/gate_closed_intervals.py`, `runtime/status.py`, `tests/*`.
* **Non‑goals:** FXCM інтеграція, зміни стору/derived, UI.
* **Інваріанти/рейки:**

  * `closed_intervals` відсортовані, не перекриваються, start<end, UTC.
  * Drift‑gate фіксує зміщення календаря без явного апдейту.
  * Без silent fallback: якщо календар невалідний → errors[]+degraded[] або hard‑fail.
* **Acceptance Criteria:**

  * `status.snapshot.degraded` НЕ містить legacy‑stub тегів.
  * `gate_closed_intervals` → OK.
  * `gate_schedule_drift` → OK.
* **Proof‑pack:**

  * `data/audit_vX/status_calendar_ok.json` — коректний статус.
  * `data/audit_vX/gate_closed_intervals.txt`.
  * `data/audit_vX/gate_schedule_drift.txt`.

---

## Фаза 2 — реальний FXCM стрім (тики)

### P8 – FXCM Tick feed (real): login/reconnect/heartbeat + strict tick rails + degrade‑loud**

* **Мета:** Увімкнути `tick_mode=fxcm` як реальну інтеграцію:

  * Стабільний логін і reconnect/backoff.
  * Heartbeat/lag у статусі.
  * Помилки (bad credentials, session drop, timeout) → гучно в errors[], зі статусом і метриками.
* **Scope:** `runtime/tick_feed.py`, `runtime/forexconnect_stream.py`, `runtime/fxcm_forexconnect.py`, `runtime/status.py`, `observability/metrics.py`, `config/config.py`, `tests/*`, `tools/exit_gates/gates/gate_fxcm_tick_liveness.py`.
* **Non‑goals:** provider history, store final, derived, UI.
* **Інваріанти/рейки:**

  * `tick_ts/snap_ts` — int ms (не ламати).
  * Reconnect не створює дубль‑потоків.
  * Логи не DDOS’ять (rate‑limit).
* **Acceptance Criteria:**

  * `gate_fxcm_tick_liveness --seconds 30` → OK (ticks>0, lag_ms sane).
  * При неправильному логіні → errors[].code=`fxcm_auth_failed`, state="error" без падіння процесу.
* **Proof‑pack:**

  * `data/audit_vX/fxcm_tick_ok.json`.
  * `data/audit_vX/fxcm_bad_login.json`.
  * `data/audit_vX/gate_fxcm_tick_liveness.txt`.

---

## Фаза 3 — FXCM історія як SSOT джерело для warmup/backfill

### P9 – FXCM History Provider: 1m final fetch (chunked, budgeted) + retry policy + determinism**

* **Мета:** Зробити `provider=fxcm` реальним у командах warmup/backfill:

  * Чанкування (обмеження барів за запит).
  * Бюджет/таймаут на одну команду.
  * Retry/backoff на transient errors.
  * Детермінованість: один і той же інтервал → однаковий результат.
* **Scope:** `runtime/fxcm/history_provider.py`, `runtime/history_provider.py`, `runtime/warmup.py`, `runtime/backfill.py`, `store/file_cache.py` (або FileCache module), `tests/*`, `tools/exit_gates/gates/gate_fxcm_history_smoke.py`.
* **Non‑goals:** stream→bar builder (це наступний slice), UI.
* **Інваріанти/рейки:**

  * Final 1m: complete=true, synthetic=false, source=history, event_ts==close_time.
  * Budget exceeded → loud error + частковий прогрес у результаті (можна resume).
  * **FileCache** використовується як основний SSOT, `legacy` SQLite тільки для тестів.
* **Acceptance Criteria:**

  * `fxcm_warmup(provider=fxcm, lookback_days=7)` → OK.
  * `gate_fxcm_history_smoke` → OK (одержано N барів, жодного контрактного відхилення).
* **Proof‑pack:**

  * `data/audit_vX/warmup_fxcm_cmd.txt`.
  * `data/audit_vX/status_after_warmup_fxcm.json`.
  * `data/audit_vX/gate_fxcm_history_smoke.txt`.

---

## Фаза 4 — “TV‑like” бари в live: з тика → preview → final

### P10 – Live Bar Builder: tick→1m finalization (market‑aware) + gap policy + no silent repairs**

* **Мета:** Будувати live‑свічки:

  * Preview: `complete=false`, часті оновлення дозволені.
  * Final: на закритті 1m — запис у FileCache як SSOT final + публікація у {NS}:ohlcv.
  * Market‑aware: не генерувати бари у `closed_intervals` або коли ринок закритий.
* **Scope:** `core/market/preview_builder.py`, `app/composition.py`, `store/file_cache.py`, `runtime/publisher.py`, `runtime/status.py`, `runtime/tail_guard.py`, `runtime/repair.py`, `tests/*`, `tools/exit_gates/gates/gate_live_final_invariants.py` (план/створити).
* **Non‑goals:** HTF derived (вже є), recovery старих періодів.
* **Інваріанти/рейки:**

  * Жодних silent repairs: якщо gap — тільки через tail_guard/repair або loud degraded.
  * Final бар формується лише коли `close_time` настав і tick‑даних достатньо.
  * NoMix enforcement зберігається.
* **Acceptance Criteria:**

  * За 30 хв live → у FileCache з’являються final 1m бари без порушень інваріантів.
  * `gate_live_final_invariants --minutes 30` → OK.
  * `gate_calendar_gaps --tf 1m --hours 1` → OK для live‑хвоста.
* **Proof‑pack:**

  * `data/audit_vX/live_30m_status.json`.
  * `data/audit_vX/gate_live_final_invariants.txt`.
  * `data/audit_vX/gate_calendar_gaps_live_tail.txt`.

---

## Фаза 5 — прод‑операційність: сервіс, рестарти, деплой, runbook

### P11 – Service hardening: restart‑safe lifecycle + locks**

* **Мета:** Гарантувати, що при рестарті не з’являються дублікати потоків, FileCache не ламається, а модулі мають чіткий start/stop state.
* **Scope:** `app/main.py`, `runtime/*` (lifecycle), `store/file_cache.py`, `tests/*`, `tools/exit_gates/gate_restart_safe.py`.
* **Non‑goals:** нові features/канали.
* **Інваріанти/рейки:**

  * Послідовність старту SSOT: 1) config 2) store 3) status 4) command_bus 5) tick_feed 6) builders.
  * `KeyboardInterrupt`/`SIGTERM` → shutdown без traceback, flush status.
* **Acceptance Criteria:**

  * `gate_restart_safe` (2 рестарти поспіль) → OK.
  * Після рестарту `status` показує адекватний uptime/reset без деградацій типу “дві підписки”.
* **Proof‑pack:**

  * `data/audit_vX/restart_1_status.json`.
  * `data/audit_vX/restart_2_status.json`.
  * `data/audit_vX/gate_restart_safe.txt`.

---

## Фаза 6 — прод‑деплой: systemd unit + профілі + secrets hygiene

### P12 – Deploy: systemd + profiles + secrets hygiene**

* **Мета:** Забезпечити прод‑деплой на VPS:

  * Написати `systemd` unit (restart=always, working dir, limits).
  * `config/profile_*.py` як SSOT для dev/stage/prod.
  * Secrets: файл/volume, шаблон, права доступу.
* **Scope:** `deploy/systemd/*.service`, `config/profile_template.py`, `config/secrets_template.py`, `docs/runbook_deploy.md`, `tools/exit_gates/gate_deploy_smoke.py`.
* **Non‑goals:** Cloudflare/proxy, UI.
* **Інваріанти/рейки:**

  * SSOT flags не в ENV.
  * У логах секрети редагуються/не друкуються.
* **Acceptance Criteria:**

  * На VPS: `systemctl status ...` → active.
  * `curl /metrics` → 200.
  * `gate_deploy_smoke` → OK (Redis/HTTP/metrics/status доступні).
* **Proof‑pack:**

  * `data/audit_vX/deploy_smoke.txt`.
  * `data/audit_vX/metrics_sample.txt`.

---

## Фаза 7 — SLO/Observability/Runbook

### P13 – Observability pack: SLO metrics + alert thresholds + runbook**

* **Мета:** Зафіксувати прод‑SLO та зробити їх видимими:

  * `tick lag` p95/p99.
  * `final 1m freshness` (now - last_complete_bar_ms).
  * Прогрес warmup/backfill.
  * Tail guard gaps/repair counts.
  * NoMix `conflicts_total`.
  * Health/heartbeat command bus.
* **Scope:** `observability/metrics.py`, `runtime/status.py`, `docs/runbook_debug.md`, `tools/exit_gates/gate_slo_minimum.py`.
* **Non‑goals:** Prometheus/Grafana (можна окремим ops‑документом).
* **Інваріанти/рейки:**

  * Метрики не створюють high‑cardinality (символи/TF — лише allowlist).
  * Чіткі пороги для алертів, описані у runbook.
* **Acceptance Criteria:**

  * `gate_slo_minimum` → OK (мінімальний набір метрик присутній, не нулі після 5 хв роботи).
  * `docs/runbook_debug.md` описує, як реагувати на алерти.
* **Proof‑pack:**

  * `data/audit_vX/metrics_dump.txt`.
  * `docs/runbook_debug.md`.

---

## Фаза 8 — дані та відтворюваність: backup/migration/replay

### P14 – Store ops: backups + migrations + replay determinism**

* **Мета:**

  * Створити консистентний backup FileCache (і SQLite, якщо legacy).
  * Відновлення на чисту машину.
  * Міграції `store/schema.sql` з явною версією (для SQLite legacy).
  * Replay: з backup → відтворити derived + перевірити гейти (deterministic).
* **Scope:** `store/schema.sql`, `store/migrations/*`, `tools/store_backup.py`, `tools/store_restore.py`, `tools/exit_gates/gate_replay_determinism.py`, `docs/runbook_recovery.md`, `tests/*`.
* **Non‑goals:** “recompute старих епох”.
* **Інваріанти/рейки:**

  * Міграції лише вперед, з версією.
  * Replay не звертається до FXCM (offline).
* **Acceptance Criteria:**

  * `backup+restore` → OK.
  * `gate_replay_determinism` → OK (final‑wire + no_mix + calendar gaps на відновленому екземплярі).
* **Proof‑pack:**

  * `data/audit_vX/backup_sha256.txt`.
  * `data/audit_vX/gate_replay_determinism.txt`.

---

## Фаза 9 — “production reality”: навантаження, мульти‑символи, деградації, hard limits

### P15 – Load/limits: caps & backpressure + multi‑symbol proof‑pack**

* **Мета:** Довести, що система витримує збільшення символів/потоку:

  * Hard caps (батчі, черги, пам’ять).
  * Політика backpressure (drop/defer) — гучно, без silent fallback.
  * Multi‑символьні метрики/статус (без high‑cardinality).
* **Scope:** `runtime/*` (queues/caps), `config/config.py`, `observability/metrics.py`, `tools/exit_gates/gate_load_smoke.py`, `tests/*`.
* **Acceptance Criteria:**

  * `gate_load_smoke --symbols XAUUSD,EURUSD,...` → OK (N хв без росту пам’яті/без deadlock).
  * `status.errors[]` порожній або містить лише очікувані loud деградації.
* **Proof‑pack:**

  * `data/audit_vX/load_10m_metrics.txt`.
  * `data/audit_vX/load_10m_status.json`.

---

## Додаткова фаза — discipline release & rollback

### P16 – Release & rollback: versioning + canary + rollback runbook**

* **Мета:** Контрольовані релізи:

  * `build_version`/`pipeline_version` — працюючі теги.
  * `canary profile` (наприклад: лише XAUUSD, лише 1m final + 15m derived).
  * Rollback інструкції + “що робити при FAIL gate”.
* **Scope:** `app/main.py`, `config/config.py`, `docs/runbook_release.md`, `tools/exit_gates/gate_canary_profile.py`.
* **Acceptance Criteria:**

  * `gate_canary_profile` → OK.
  * Rollback runbook описує: stop service → restore backup → replay gates → start.
* **Proof‑pack:**

  * `docs/runbook_release.md`.
  * `data/audit_vX/gate_canary_profile.txt`.

---

Цей список відображає поточну дорожню карту з урахуванням зміщення SSOT на **FileCache**. Якщо з’являться нові зміни в архітектурі або вимогах, відповідні P‑slice будуть адаптовані.
