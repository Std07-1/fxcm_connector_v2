1) 12 жорстких пунктів: як зафіксувати нормативно (щоб це було виконувано)
1.1. TF allowlist (канонічна множина)

Нормативно (і для producer, і для validator, і для status):

TF_ALLOWLIST = {"1m","5m","15m","1h","4h","1d"}
Будь-що інше → ContractError / errors[] (no silent fallback).

1.2. bars[].source allowlist + норматив для final

Нормативні значення:

SOURCE_ALLOWLIST = {"stream","history","history_agg","synthetic"}

FINAL_SOURCES = {"history","history_agg"}

Норматив для final (complete=true) — строго:

synthetic=false

source ∈ FINAL_SOURCES

уніформно в межах batch (або валідатором заборонити змішування в одному message).

Якщо у проді “stream як final” інколи трапляється — або заборонити і виправити producer, або формалізувати як виняток з окремим major bump, бо “NoMix” і детермінізм одразу ускладнюються.

1.3. Tick time units — однозначно ms int

У NS:price_tik закріпити:

tick_ts: int (UTC epoch ms)

snap_ts: int (UTC epoch ms)

Validator:

fail-fast, якщо float або “seconds-like” значення (наприклад < 10^12 для сучасних дат).

1.4. close_time — інклюзивна модель

Нормативно:

Бар представляє інтервал [open_time, close_time] inclusive

Для 1m: close_time = open_time + 60_000 - 1

Для HTF: close_time = bucket_end_ms - 1

Це робить правило event_ts == close_time математично чистим.

1.5. Сортування/дедуп всередині payload

Нормативно:

bars MUST бути відсортовані за open_time зростанням

bars MUST не містити дублікати open_time

batch MUST бути “однорідний”: один symbol, один tf

1.6. Max batch size (операційний ліміт)

Нормативно додати:

max_bars_per_message (рекомендовано 512 або 1024)

producer MUST chunk-ити warmup/backfill/republish

Це захищає Pub/Sub і консюмерів.

1.7. Final-wire: event_ts для final — MUST існувати

Щоб перестати гадати “де істинний час події”, для final:

event_ts MUST існувати

event_ts == close_time

complete=true, synthetic=false

(Для preview event_ts або відсутній, або має іншу семантику — але це краще не вводити взагалі.)

1.8. Bucket boundary rail (календарний)

Для final:

open_time MUST бути вирівняний під bucket boundary функцією з SSOT календаря (інакше producer/validator роз’їдуться).

1.9. “No mixing” — формулювання як rail

Нормативно:

Для одного (symbol, tf, open_time) серед повідомлень з complete=true заборонено мати два різні bars[].source.

Preview може “шуміти”, але final — стабільний.

1.10. Trading day boundary (1d) — параметр конфігу + calendar_tag

Нормативно:

trading_day_boundary_utc = "22:00" (або інше, але тільки з конфігу SSOT)

У status MUST бути calendar_tag, щоб UI/ops бачили, який календар активний.

1.11. closed_intervals_utc — один формат, один сенс

Нормативно вибрати один формат (рекомендую epoch ms):

список інтервалів [start_ms, end_ms) (напіввідкритий)
Це зручно для календарної логіки й не конфліктує з інклюзивним close_time барів.

1.12. Команди: мінімальний ACK-стандарт через status snapshot

Нормативно:

req_id MUST бути унікальним у межах процесу (краще UUIDv7 або монотонний ID)

last_command.state ∈ {"running","ok","error"}

unknown cmd → errors[] містить code="unknown_command", last_command.state="error"

2) Мінімальний delta до docs/public_api_spec.md (готові вставки)

Нижче — текст, який можна вставити точково, без переписування всього документа.

### (NEW) 2.2.X. Порядок і унікальність барів у batch (нормативно)

- `bars` MUST бути відсортовані за `open_time` у зростаючому порядку.
- `bars` MUST не містити дублікати `open_time`.
- batch MUST описувати рівно один `(symbol, tf)`.

### (NEW) 2.2.Y. Limits (операційні)

- `max_bars_per_message`: 1024 (або інше значення зі збірки, але має бути зафіксовано).
- Producer MUST chunk-ити warmup/backfill/republish, щоб не публікувати надвеликі повідомлення.

### (UPDATE) 2.2.4. Семантика часу (уточнення close_time)

- Бар представляє інтервал [open_time, close_time] inclusive.
- Для `1m`: `close_time = open_time + 60_000 - 1`.
- Для HTF: `close_time = bucket_end_ms - 1`.

### (UPDATE) 2.2.5 / final-wire (event_ts)

Для final (`complete=true`) bar MUST:
- `synthetic=false`
- `event_ts` MUST існувати і дорівнювати `close_time`

### (UPDATE) 2.3. Tick time units (зняти двозначність)

У `NS:price_tik`:
- `tick_ts: int` (UTC epoch ms)
- `snap_ts: int` (UTC epoch ms)
Validator: fail-fast якщо float або seconds.

### (UPDATE) 3.2. 1d boundary як параметр конфігу + calendar_tag

- `trading_day_boundary_utc` задається в SSOT конфігу конектора.
- `calendar_tag` публікується у `NS:status:snapshot`, щоб клієнти бачили активний календар.

### (UPDATE) 2.5. Commands unknown_command

Якщо команда невідома:
- `errors[]` містить `code="unknown_command"`
- `last_command.state="error"`

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