Нижче — **початкова інструкція (Development Constitution)** для Copilot і GPT. Її мета: зафіксувати рейки, інваріанти, межі, процес і Definition of Done так, щоб під час розробки “чистого конектора” ми **не відхилялися** і завжди мали один SSOT-орієнтир.

Скопіюй це як `docs/DEV_CONSTITUTION.md` (або `docs/copilot_instructions.md`) і використовуй як префікс у кожній сесії з Copilot/GPT.

---

# FXCM Connector vNext — Development Constitution (SSOT)

## 0) Мета і незмінні принципи

### 0.1. Мета

Побудувати **новий чистий конектор** з контрактною, детермінованою Public Surface у Redis:

* **UI** отримує **Preview** (може бути incomplete, часті оновлення, живі свічки на всіх TF).
* **SMC/аналітика** отримує **Final** (тільки complete=true, synthetic=false; HTF final строго derived з SSOT 1m final).

### 0.2. Принципи (must)

* **SSOT**: один документ правди для Public API (`docs/public_api_spec.md`) і один SSOT для часу/календаря в коді.
* **Contract-first**: будь-який payload на дроті валідований runtime validator-ом (fail-fast).
* **No silent fallback**: деградації тільки “degraded-but-loud” через `errors[]/degraded[]` або явну відмову.
* **DRY/SoC**: календар/час, валідатор, паблішер, FXCM thread, store — розділені.
* **Dependency rule**: доменні/контрактні модулі не імпортують runtime/IO; composition root тільки в `app/main.py`.
* **Мінімальні P-slices**: невеликі інкременти з exit gates, без “великих рефакторів”.

---

## 1) Public Surface — незмінні інваріанти (must)

### 1.1. Namespace

* Усі Redis ресурси працюють у `NS` (`{NS}:ohlcv`, `{NS}:price_tik`, `{NS}:status`, `{NS}:status:snapshot`, `{NS}:commands`).
* Клієнти **не хардкодять** `fxcm:*`, використовують `NS` з конфігу.

### 1.2. OHLCV: Preview vs Final

**Preview (для UI):**

* `complete=false` дозволено.
* Часті апдейти поточного бару дозволені.
* Може співіснувати з Final, але не є “істиною”.

**Final (істина для SMC):**

* `complete=true` MUST
* `synthetic=false` MUST
* `event_ts` MUST існувати і дорівнювати `close_time`
* HTF final (`15m/1h/4h/1d`) MUST бути **derived з SSOT 1m final**
* **NoMix final**: для `(symbol, tf, open_time)` серед `complete=true` заборонено 2 різні `bars[].source`

### 1.3. Канонічні множини значень (must)

* `TF_ALLOWLIST = {"1m","5m","15m","1h","4h","1d"}`
* `SOURCE_ALLOWLIST = {"stream","history","history_agg","synthetic"}`
* `FINAL_SOURCES = {"history","history_agg"}`

Будь-яке значення поза allowlist → fail-fast (ContractError) або loud error у статусі.

### 1.4. Час (must)

* `open_time/close_time` — UTC epoch **ms** (int).
* Бар представляє інтервал **[open_time, close_time] inclusive**.
* 1m: `close_time = open_time + 60_000 - 1`
* HTF: `close_time = bucket_end_ms - 1`
* Final: `event_ts == close_time`

### 1.5. Batch правила (must)

* `bars` MUST відсортовані за `open_time` (strict ascending).
* `bars` MUST не містять дублікатів `open_time`.
* batch MUST описує рівно один `(symbol, tf)`.

### 1.6. Tick time units (must)

У `{NS}:price_tik`:

* `tick_ts: int` (UTC epoch ms)
* `snap_ts: int` (UTC epoch ms)
  Validator fail-fast на float/seconds.

### 1.7. Limits (must)

* `max_bars_per_message` — зафіксовано (1024 за замовчуванням).
* Producer MUST chunk-ити warmup/backfill/republish.

---

## 2) Календар і 1d boundary — SSOT (must)

### 2.1. Trading time

Trading time визначається календарем, не “суцільним UTC”. Підтримує:

* daily break
* weekend close/open
* `closed_intervals_utc` (expected closed windows)

### 2.2. 1d boundary

* `trading_day_boundary_utc` — параметр SSOT конфігу (наприклад `"22:00"`).
* Одна функція розрахунку boundary використовується **і в агрегації, і у валідаторі, і у tail_guard**.
* `status:snapshot` MUST містити `calendar_tag`.

### 2.3. Формат closed_intervals_utc (must)

* epoch ms, інтервали **[start_ms, end_ms)**

---

## 3) Архітектурні рейки (must)

### 3.1. Threading / IO модель (must)

* Уся взаємодія з ForexConnect — **в одному FXCM thread**.
* Решта системи звертається через `queue` (requests/responses).
* Історичні запити budgeted: token bucket + single in-flight.

### 3.2. Внутрішній SSOT store (must)

* Конектор має локальний SSOT 1m final (рекомендовано SQLite WAL).
* HTF final derived з 1m final (rebuild), а не “як прийшло зі стріму”.

### 3.3. Runtime validator (must)

* Валідатор дозволяє тільки allowlist полів/типів.
* Забороняє “зайві поля” без оновлення allowlist.
* Помилки контракту — fail-fast у producer-коді та loud у статусі.

### 3.4. Status як операційний SSOT (must)

* `{NS}:status` — стрім подій стану.
* `{NS}:status:snapshot` — останній повний snapshot.
* У snapshot MUST бути:

  * `version/build_version/pipeline_version/schema_version` (мінімум у статусі)
  * `errors[]/degraded[]`
  * `last_command` з `state ∈ {"running","ok","error"}`

---

## 4) Команди (must)

### 4.1. Public commands (мінімум)

* `fxcm_warmup`
* `fxcm_backfill`
* `fxcm_tail_guard`
* `fxcm_republish_tail`

### 4.2. ACK без окремого каналу (must)

* Відповідь на команду відображається в `status:snapshot.last_command` + `errors[]`.
* unknown command → `errors[].code="unknown_command"`, `last_command.state="error"`.
* `req_id` MUST бути унікальним у межах процесу.

---

## 5) Exit Gates (must) — Definition of Done для кожного slice

Кожний P-slice вважається завершеним тільки якщо:

1. Є **PRE/POST запис у журналі** (append-only) з:

   * що/чому/інваріанти/ризики
   * як перевірено
2. Мінімальний диф: без “масових рефакторів”, лише потрібні файли.
3. Є хоча б:

   * 1–3 тести (positive/negative/edge) **або**
   * runtime rail у вузькому місці + відтворюваний локальний сценарій перевірки
4. Пройдений відповідний exit gate:

**Gates мінімум:**

* Gate-OHLCV-Geom: інваріанти OHLC на хвості N год без порушень
* Gate-Calendar-Gaps: unexpected_missing_bars == 0 у trading time на хвості N год (allowlist TF)
* Gate-Final-Wire: final має `complete=true, synthetic=false, event_ts==close_time, source=history_agg`
* Gate-NoMix: відсутні конфлікти final-source для `(symbol, tf, open_time)`

---

## 6) Планування розробки (must process)

### 6.1. Режими роботи

* MODE=read-only discovery: лише факти з `path:line`, без змін коду.
* MODE=PATCH: мінімальний slice, рейки/тести, exit gate.
* MODE=ADR-only: фіксація одного рішення + інваріанти.

### 6.2. Заборони (hard)

* Заборонено додавати нові поля у payload без оновлення allowlist validator-а.
* Заборонено вводити “тимчасові фолбеки” без `errors[]/degraded[]`.
* Заборонено змішувати preview/final як істину.
* Заборонено робити HTF final напряму зі стріму: лише rebuild з 1m final SSOT.

---

## 7) Мінімальний легкий чарт (must, ранній)

Щоб не працювати “всліпу”, з самого початку планується внутрішній read-only chart:

* `GET /api/status` (показує status snapshot)
* `GET /api/bars?...` (читання зі store)
* `WS /ws/live?...` (preview/final/both)
* Відображення: candles + позначки complete/synthetic + gap markers

Цей чарт є опорним інструментом відладки конектора, незалежним від SMC/UI_v2.

---

## 8) Мовні правила (must)

* Усі докстрінги/коментарі/логи — українською.
* Імена класів/функцій/метрик — англійською.

## 12 жорстких пунктів: як зафіксувати нормативно (щоб це було виконувано)
1.1. TF allowlist, SOURCE allowlist, FINAL_SOURCES

Нормативно (і для producer, і для validator, і для status):

TF_ALLOWLIST = {"1m","5m","15m","1h","4h","1d"}

SOURCE_ALLOWLIST = {"stream","history","history_agg","synthetic"}

FINAL_SOURCES = {"history","history_agg"}

Будь-що поза allowlist → MUST fail-fast (ContractError) або errors[] (no silent fallback).

1.2. Tick time units — однозначно ms int

У NS:price_tik:

tick_ts: int (UTC epoch ms)

snap_ts: int (UTC epoch ms)

Validator MUST fail-fast на float або seconds-like значення (наприклад < 10^12).

1.3. close_time — інклюзивна модель

Нормативно:

Бар представляє інтервал [open_time, close_time] inclusive.

Для 1m: close_time = open_time + 60_000 - 1.

Для HTF: close_time = bucket_end_ms - 1.

1.4. Сортування/дедуп всередині payload

Нормативно:

bars MUST бути відсортовані за open_time зростанням.

bars MUST не містити дублікати open_time.

batch MUST бути однорідний: один symbol, один tf.

1.5. Max batch size (операційний ліміт)

Нормативно:

max_bars_per_message = 1024 (за замовчуванням, або інше зафіксоване значення).

Producer MUST chunk-ити warmup/backfill/republish.

1.6. Final-wire: complete/synthetic/event_ts

Для final (complete=true):

synthetic=false MUST.

event_ts MUST існувати і бути == close_time.

source MUST ∈ FINAL_SOURCES.

1.7. NoMix для final

Для одного (symbol, tf, open_time) серед повідомлень з complete=true заборонено мати два різні bars[].source.

1.8. Trading day boundary (1d) + calendar_tag

trading_day_boundary_utc MUST задаватися в SSOT конфігу.

У status:snapshot MUST бути calendar_tag.

1.9. closed_intervals_utc — один формат

Нормативно: epoch ms, інтервали [start_ms, end_ms) (напіввідкритий формат).

1.10. Команди: мінімальний ACK-стандарт через status snapshot

req_id MUST бути унікальним у межах процесу (краще UUIDv7 або монотонний ID).

last_command.state ∈ {"running","ok","error"} MUST.

unknown command → errors[] містить code="unknown_command", last_command.state="error".

1.11. Версії у status snapshot

status:snapshot MUST містити schema_version, pipeline_version, build_version (мінімальний набір).

1.12. Internal keys правило

Внутрішні ключі (watermark/ttl/mark-и) MUST NOT бути Public Surface; їх семантика не документується як Public API.

2) Мінімальний delta до docs/public_api_spec.md (готові вставки)

Нижче — текст, який можна вставити точково, без переписування всього документа.

### (NEW) 2.2.X. Порядок і унікальність барів у batch (нормативно)

* `bars` MUST бути відсортовані за `open_time` у зростаючому порядку.
* `bars` MUST не містити дублікати `open_time`.
* batch MUST описувати рівно один `(symbol, tf)`.

### (NEW) 2.2.Y. Limits (операційні)

* `max_bars_per_message`: 1024 (або інше значення зі збірки, але має бути зафіксовано).
* Producer MUST chunk-ити warmup/backfill/republish, щоб не публікувати надвеликі повідомлення.

### (UPDATE) 2.2.4. Семантика часу (уточнення close_time)

* Бар представляє інтервал [open_time, close_time] inclusive.
* Для `1m`: `close_time = open_time + 60_000 - 1`.
* Для HTF: `close_time = bucket_end_ms - 1`.

### (UPDATE) 2.2.5 / final-wire (event_ts)

Для final (`complete=true`) bar MUST:
* `synthetic=false`
* `event_ts` MUST існувати і дорівнювати `close_time`

### (UPDATE) 2.3. Tick time units (зняти двозначність)

У `NS:price_tik`:
* `tick_ts: int` (UTC epoch ms)
* `snap_ts: int` (UTC epoch ms)
Validator: fail-fast якщо float або seconds.

### (UPDATE) 3.2. 1d boundary як параметр конфігу + calendar_tag

* `trading_day_boundary_utc` задається в SSOT конфігу конектора.
* `calendar_tag` публікується у `NS:status:snapshot`, щоб клієнти бачили активний календар.

### (UPDATE) 2.5. Commands unknown_command

Якщо команда невідома:
* `errors[]` містить `code="unknown_command"`
* `last_command.state="error"`

3) Вимога “живі свічки на всіх TF” (TV-like) — як це зробити правильно

Це означає: UI хоче бачити preview candles на 1m/5m/15m/1h/4h/1d, але SMC має брати тільки final.

3.1. Розділити producer на два контури: Preview Builder vs Final Builder

Preview Builder (для UI):

Джерело: live 1m (і/або ticks)

Будує “поточний бар” кожного TF інкрементально

Публікує часті апдейти

Правила:

complete=false (для поточного bucket)

synthetic зазвичай false (краще не вводити synthetic у preview без крайньої потреби)

source="stream" (або "stream_agg" якщо хочете окремо, але тоді це ще одна множина — небажано)

Final Builder (істина для SMC):

Джерело: SSOT 1m final store

Запускається тільки на закритті bucket (за календарем)

Публікує final:

complete=true, synthetic=false, source="history_agg", event_ts==close_time

3.2. “No mixing” при співіснуванні preview/final

Ви вже правильно формалізували: “NoMix” застосовувати тільки до complete=true.

UI може отримувати preview, але:

не має показувати preview як final

final завжди має “перекривати” preview для того самого (symbol, tf, open_time).

Практичний механізм для UI:

dedup key (symbol, tf, open_time)

якщо прийшов final → він перемагає незалежно від ingest_ts

4) Політика FXCM: “не штурмувати”, але мати контрольований backfill навіть коли ринок закритий
4.1. Request Budget + single FXCM thread

Щоб не повторити “ForexConnect кошмар”, робіть так:

Один thread володіє ForexConnect (усі API calls тільки там).

Усі інші частини — через черги request_q/response_q.

Додайте простий token bucket:

ліміт історичних запитів/хв

ліміт паралельності = 1 in-flight

backoff/jitter на помилки

4.2. “Probe-first” стратегія

На старті і при tail_guard:

спочатку перевірка локального store + календар (де взагалі мають бути бари)

потім малий probe window (наприклад 60–180 хв 1m)

тільки якщо є пропуски — план ремонту з chunk-ами, не суцільний “штурм”

4.3. Командний режим “force history when market closed”

Ви це хочете — і це нормально, але:

це має бути явна команда (fxcm_backfill або fxcm_tail_guard(repair=true))

результат повинен бути loud:

або ok

або error з деталями в errors[] (код/контекст/діапазон)

5) Retention 365 днів “по всіх TF” — як забезпечити без самообману

Ключове: ви вже задали інваріант “HTF final будується з SSOT 1m final”. Тому мінімально достатньо зберігати 365 днів 1m final, а HTF:

або rebuild-on-demand,

або зберігати як cache, але завжди відтворюваний з 1m.

Рекомендація (практична)

SQLite (WAL) як SSOT store:

таблиця bars_1m_final (індекс (symbol, open_time))

додатково (опційно) cache таблиці bars_15m_final, bars_1h_final, ... з позначкою derived_from_1m=true

Плюс “ledger” для перевірок (див. розділ 6).

6) Tail-guard + “позначки перевірено/не перевірено” (щоб не палити ресурси)

Тут потрібні дві речі:

6.1. Алгоритм tail_guard (календарний, не “суцільний UTC”)

Визначити trading-time інтервали в [now - window_hours, now] з урахуванням:

weekend close/open

daily break

closed_intervals_utc

Для кожного TF:

згенерувати expected bucket open_time (канонічно)

порівняти з store

знайти missing segments

Скласти repair plan: мінімальні ділянки 1m, які треба backfill-нути

Після backfill:

rebuild touched HTF

republish tail (optionally force)

6.2. “Позначки перевірено” (audit ledger)

Внутрішньо (не Public API) додайте ledger, наприклад таблиця:

tail_audit_state(symbol, tf, verified_until_ms, last_audit_ts_ms, last_gap_count, last_ok_ts_ms, etag_or_hash?)

Правило:

Якщо verified_until_ms уже покриває діапазон і не було “touch” (backfill/rebuild) — tail_guard не робить повторних важких перевірок.

Якщо repair торкнувся діапазону — інваліднути verified marker тільки на touched range.

У status:snapshot корисно показувати (це вже Public Surface як статус):

tail_guard_state.verified_until_ms

tail_guard_state.last_gap_count

tail_guard_state.last_audit_ts_ms

7) Власний легкий чарт (обов’язково, інакше ви реально працюєте всліпу)

Вам потрібен мінімальний read-only chart саме для конектора, незалежний від SMC/UI_v2.

7.1. Мінімальна функціональність

Вибір symbol, tf, режим preview/final/both

Candles + об’єм

Візуальні маркери:

complete (final vs preview)

synthetic (має бути видно відразу)

“gap markers” (expected bar відсутній у store)

Панель статусу:

calendar_tag, market.is_open, last_complete_bar_ms, lag_s, tail_guard_state

7.2. Технічна реалізація (проста і надійна)

HTTP сервер всередині конектора (наприклад, http.server або легкий ASGI)

Endpoint-и:

GET /api/status → зчитати NS:status:snapshot

GET /api/bars?symbol=XAUUSD&tf=15m&mode=final&from_ms=...&to_ms=...

читає зі store (SSOT), не з Redis

WS /ws/live?symbol=...&tf=...&mode=preview|final|both

стрімить те, що конектор сам публікує/будує

UI:

статична HTML сторінка + lightweight-charts

без авторизації, але bind на localhost або за reverse-proxy правилами

Цей чарт стане вашим “осцилографом” конектора: видно реальну геометрію свічок, видно календарні розриви, видно чи final реально детермінований.

8) P-slices (перебудовано з урахуванням чарту і 365d)
P0 — Skeleton + Public Surface + Validator + Status

Redis pub/sub writer

NS:status + NS:status:snapshot

NS:commands subscriber (unknown_command → errors[])

контрактний валідатор для ohlcv/tick/status/commands

Chart P0: GET /api/status + мінімальна HTML сторінка (показує snapshot)

Exit gate: “можна запустити процес, надіслати невідому команду, побачити error у snapshot”.

P1 — Tick feed (strict ms) + chart live tick

NS:price_tik з tick_ts/snap_ts int ms

status: tick lag/heartbeat

chart: показ tick/спред

P2 — Preview candles на всіх TF (TV-like)

1m preview + інкрементальний preview builder для 5m/15m/1h/4h/1d

frequent updates, але complete=false

chunk/limits

Exit gate: Gate-OHLCV-Geom на preview хвості (без “битих” свічок).

P3 — SSOT 1m final store + warmup/backfill (365d)

SQLite WAL store

warmup: загрузити 365d 1m final (порційно, budgeted)

publish tail (chunked)

Exit gate: Gate-Calendar-Gaps (1m) на allowlist TF (мінімум 1m).

P4 — Final derived rebuild (history_agg) + final-wire

rebuild 15m/1h/4h/1d з 1m final

event_ts==close_time, source=history_agg

публікація final у NS:ohlcv

Exit gate: Gate-Final-Wire.

P5 — Tail guard + audit ledger (verified markers)

календарний аудит хвоста

repair plan + backfill + rebuild + republish(force)

ledger verified_until_ms, invalidation on touch

Exit gate: unexpected_missing_bars == 0 на хвості після repair.

P6 — NoMix enforcement

детектор конфлікту final-source → loud error/degraded

опційно: блок publish final до ручного втручання (краще як “режим безпеки” в конфігу)

Exit gate: Gate-NoMix.

9) Дві речі, які я б додав “одразу” як рейки (бо вони ловлять 80% болю)

Seconds-vs-ms rail (tick і ohlcv часи):
будь-яке значення часу < 10^12 для сучасних дат → ContractError з чітким повідомленням.

Bucket-boundary rail (final):
якщо open_time не вирівняний під календарну bucket boundary → final publish заборонити і підняти errors[].

Якщо ви підете цим шляхом, у вас буде:

чітка Public Surface (Redis) з fail-fast контрактами,

детермінований final (SMC-істина),

UI-friendly preview на всіх TF (TV-like),

365d історія як реальний SSOT,

tail_guard без “безкінечних штурмів”,

і головне — власний легкий чарт, який покаже правду про свічки/календар/прогалини ще до того, як ви вбудуєте це в SMC.