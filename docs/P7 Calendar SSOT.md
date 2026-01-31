# P7 Calendar SSOT

## P7 Calendar SSOT у `Std07-1/fxcm_connector_v2`: глибинний аудит реалізації, рейок і залишкових ризиків

## Контекст P7 і що саме потрібно довести

У дорожній карті (Audit v7_1a) P7 визначено як заміну stub‑календаря на **реальний SSOT‑календар**, де:
- `is_open`, `next_open_utc`, `next_pause_utc` працюють коректно,
- `closed_intervals` беруться з SSOT‑даних (JSON),
- додані гейти `schedule_drift` та `closed_intervals` validity,
- відсутній silent fallback: невалідний календар має бути “loud” через `errors[]` + `degraded[]` або hard‑fail.

Acceptance criteria в тому ж документі формально зводяться до трьох тверджень: `status.snapshot.degraded` не містить stub‑тегів, гейти для closed intervals і schedule drift дають `OK`.

Нижче — перевірка по **фактичному коду `main`**, зі зв’язуванням “що є” ↔ “що вимагалось”, плюс список ризиків, які **вже не про stub**, але напряму впливають на “прод‑придатність календаря”.

## Реалізація SSOT‑календаря в `core/time/*`

### Де SSOT і як він підтягується

SSOT для календарних правил у репозиторії реалізовано як JSON‑профілі в `config/calendar_overrides.json` з ключем `calendar_tag` (наразі два профілі).

Клас `Calendar` (`core/time/calendar.py`) **на старті завжди** намагається завантажити overrides з `config/calendar_overrides.json` через `load_calendar_overrides(...)` і `calendar_tag`. Будь‑яка помилка парсингу/валідації вважається `init_error`. fileciteturn7file0turn8file0

Критично важливий rail: якщо в `Calendar` хтось спробує передати `closed_intervals_utc` напряму (не порожній список) — це **не “fallback”**, а ініціалізаційна помилка з явним повідомленням, що SSOT — тільки JSON.

Це прямо закриває вимогу “SSOT лише в даних” і “без silent fallback”: ін’єкція інтервалів ззовні не приймається тихо, вона ламає календар у стан `init_error`. fileciteturn7file0turn31file0

### Формат і рейки `closed_intervals_utc`

Нормалізація/валідація `closed_intervals_utc` централізована в `core/time/closed_intervals.py` функцією `normalize_closed_intervals_utc(...)`. Вона enforce‑ить:
- тип “список списків/кортежів”,
- рівно два елементи на інтервал,
- `start_ms` і `end_ms` — `int` (не `bool`),
- межі epoch rails через `MIN_EPOCH_MS/MAX_EPOCH_MS`,
- `start_ms < end_ms`,
- сортування за `start_ms`,
- відсутність overlap (`cur.start < prev.end` → помилка). fileciteturn9file0turn40file0

Це практично повний збіг з P7‑інваріантами “відсортовані, не перекриваються, start<end, UTC(epoch ms)”. fileciteturn33file0turn9file0

### Сесійна семантика `is_open/next_open/next_pause`

Вся семантика сесій реалізована у `TradingCalendar` (`core/time/sessions.py`):
- `is_trading_time(ts_ms)` повертає `False` якщо `init_error` або час попадає у `closed_intervals_utc`, у weekend close, або у daily break (для Mon‑Thu).
- `next_trading_open_ms(ts_ms)` знаходить наступний старт торгового інтервалу, враховуючи daily break і weekend boundary, а також “перестрибує” через `closed_intervals_utc` (якщо candidate попадає в closed interval, рекурсивно шукає далі).
- `next_trading_pause_ms(ts_ms)` повертає найближчу паузу (кінець поточного open‑інтервалу), але додатково вміє виявляти `closed_intervals_utc`, що починаються всередині open‑інтервалу, і тоді pause стає стартом такого closed interval.
- `market_state(ts_ms)` віддає `is_open`, `next_open_utc`, `next_pause_utc`, `calendar_tag`, `tz_backend`. fileciteturn8file0turn34file0

`Calendar.market_state(...)` делегує у `TradingCalendar.market_state(...)`, але якщо є `init_error`, то повертає “safe‑closed” з `tz_backend="init_error"` і `next_open_utc/next_pause_utc` виставленими в поточний UTC‑ISO (щоб payload завжди був валідний і не ламав status). fileciteturn7file0turn34file0

Окремо важливо: `Calendar.is_open/next_open_ms/next_pause_ms` при `init_error` повертають safe‑опції (False або поточний `ts_ms`). Це узгоджується з “degraded‑but‑loud”, а не з “тихою підміною” якихось правил. fileciteturn7file0turn31file0

### Які саме профілі є в SSOT зараз

`config/calendar_overrides.json` містить два профілі:
- `fxcm_calendar_v1_ny`: `tz_name="America/New_York"`, weekly open/close 17:00, daily break 17:00 на 5 хв, є `closed_intervals_utc` (epoch ms) та `holiday_policy` (required=false, min_future_days=0).
- `fxcm_calendar_v1_utc_overrides`: `tz_name="UTC"`, weekly open 23:01, weekly close 21:45, daily break 22:00 на 61 хв, є `closed_intervals_utc` (epoch ms) та `holiday_policy` (required=false, min_future_days=0). fileciteturn10file0turn45file0turn44file0

Канонічна інтерпретація `holiday_policy` у цьому режимі: `closed_intervals_utc` підтримує “known closures/maintenance”, але **не гарантує** повне покриття свят наперед.
Gate `gate_calendar_holiday_policy` тут виконує **структурну** перевірку даних (формат/кількість/узгодженість), а не coverage‑гарант.

Розмежування профілів: runtime SSOT — `fxcm_calendar_v1_ny` (DST‑aware NY rollover для торгового schedule). Профіль `fxcm_calendar_v1_utc_overrides` використовується як контрольний/спеціальний (наприклад, XAU gate або бек‑порівняння), а не як дефолтний runtime‑schedule.

Факт міграції підтверджується наявністю `tools/migrate_v1_calendar_overrides.py`, який читає v1 формат (ISO `start/end` + `holidays`) і записує нормалізований список в `fxcm_calendar_v1_utc_overrides` у `calendar_overrides.json`. fileciteturn44file0turn45file0

## Exit gates і тестове покриття: що реально зафіксовано

### Gate для валідності `calendar_overrides.json` і `closed_intervals_utc`

`gate_calendar_closed_intervals`:
- читає `config/calendar_overrides.json`,
- перевіряє, що це список профілів,
- enforce‑ить ключі schedule (`weekly_open/weekly_close/daily_break_start/daily_break_minutes/tz_name`) і значення (HH:MM, int>0, TZ резолвиться),
- проганяє `normalize_closed_intervals_utc(...)` для `closed_intervals_utc` кожного профілю. fileciteturn12file0turn9file0turn8file0

### Gate holiday_policy (структурний)

`gate_calendar_holiday_policy`:
- перевіряє типи/обов’язкові поля policy,
- валідовує `closed_intervals_utc` через `normalize_closed_intervals_utc(...)`,
- enforce‑ить `len(closed_intervals_utc) >= min_intervals` та узгодженість `coverage_end_utc == max(end_ms)`.

### Gate для “schedule drift” і що він насправді ловить

`gate_calendar_schedule_drift`:
- завантажує runtime config (`load_config()`),
- створює `Calendar([], config.calendar_tag)` і фейлить, якщо календар має `init_error`,
- паралельно вантажить overrides для того ж `calendar_tag`,
- перевіряє, що:
  - за хвилину до daily break календар OPEN,
  - через хвилину після старту break — CLOSED,
  - через хвилину після weekly close — CLOSED,
  - через хвилину після weekly open — OPEN. fileciteturn13file0turn7file0turn8file0turn20file0

Ключовий нюанс (важливо для інтерпретації “drift”): gate **не порівнює** календар із якимось “еталоном поза SSOT” (наприклад, з FXCM‑розкладом або зашитими константами). Він фактично ловить:
- відрив реалізації `Calendar/TradingCalendar` від SSOT overrides (якщо код перестане читати JSON або почне інтерпретувати час неправильно),
- проблеми TZ‑резолву/конвертації (зсуви через tz backend),
- регресії у правилах break/week boundary.

Тобто gate — це **регресійний “drift від SSOT”**, а не “drift від реального ринку”. Це відповідає формулюванню P7 “drift без явного апдейту” у сенсі: код не має “дрейфувати” від SSOT непомітно.

### Включення гейтів у дефолтний manifest

У `tools/exit_gates/manifest.json` гейти `gate_calendar_closed_intervals` та `gate_calendar_schedule_drift` входять у дефолтний набір.

Це підкріплено тестом `tests/test_manifest_includes_calendar_gates.py`, який перевіряє, що обидва ID є у manifest.

### Календарні тести: що покрито реально

Є два “шари” тестів:

1) **Тести на завантаження SSOT overrides**: `test_calendar_overrides_loading_for_tags` гарантує, що обидва профілі зчитуються і мають очікувані атрибути (TZ, daily_break_minutes).

2) **Тести на семантику сесій/меж**:
- `tests/test_calendar_sessions.py` перевіряє:
  - `next_pause_ms` на межі daily break,
  - `next_open_ms` після break,
  - weekend boundary,
  - DST boundary (pre/post DST Sunday open дає різний UTC час).
- `tests/test_calendar_schedule_semantics.py` параметризовано перевіряє open/close/break для обох профілів (NY і UTC overrides), і окремо тестує `Calendar` з tmp overrides файлом (тобто шлях `overrides_path` працює).
- `tests/test_calendar_closed_interval_effect.py` перевіряє, що `closed_intervals_utc` реально блокує trading_time.
- `tests/test_calendar_xau_profile.py` фіксує очікуване `next_open_ms` = 23:01 UTC для `fxcm_calendar_v1_utc_overrides` (weekend reopen і reopen після daily break).

У сумі це означає: вимога “коректні `is_open`, `next_open`, `next_pause`” не просто задекларована, а **закрита тестами на boundary‑сценарії**, включно з DST для NY профілю.

## Surfacing у runtime: як виглядає “degraded‑but‑loud” на практиці

### Status snapshot більше не має stub‑тегів як деградації

У `runtime/status.py` деградація календаря робиться через тег `calendar_error`:
- `StatusManager._ensure_calendar_health()` перевіряє `calendar.health_error()` і якщо він є, додає `"calendar_error"` у `degraded` і додає error‑об’єкт з `code="calendar_error"`.
- `build_initial_snapshot()` робить те ж саме при старті (щоб вже перший snapshot був “loud”, якщо календар невалідний).

У самому репозиторії згадки stub‑календаря лишаються лише в історичних артефактах; у runtime‑коді їх немає.
Тобто в “живому runtime” (модулі, які імпортуються й виконуються) stub‑тегів деградації **немає**.

Це рівно закриває acceptance criteria “`status.snapshot.degraded` НЕ містить stub‑тегів” — принаймні на рівні коду, який формує degraded‑теги.

### Як календар врізається в runtime‑composition

`app/composition.py` створює `Calendar` під runtime як `Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)`.

Тут важливий практичний наслідок рейки “SSOT лише JSON”: будь‑які спроби ін’єкції closed‑інтервалів поза `calendar_overrides.json` блокуються через `init_error`, а status автоматично стає `calendar_error` (degraded + errors[]).

### Де календар критично впливає на поведінку системи

Календар використовується не лише для “гарного status”, а як реальний rail:
- `runtime/history_provider.guard_history_ready()` пише в status `next_trading_open_ms` через `calendar.next_open_ms(...)`, тобто backoff/readiness логіка історії прямо залежить від календаря.
- `runtime/tail_guard.py` використовує `calendar.is_open(...)` при пошуку missing ranges (не рахувати дірки в hours/days коли ринок закритий), а також “repair дозволено лише коли ринок закритий” через `calendar.is_repair_window(...)`.

Це підсилює вимогу P7 “без silent fallback”: якщо календар “бреше”, він створює хвилю вторинних дефектів (неправильні gaps, неправильна відкладена репарація, тощо).

## Залишкові ризики і “тонкі місця” після виконання P7

### Документація потребує синхронізації

- `docs/calendar_sessions_spec.md` має TODO про holiday‑інтервали для `fxcm_calendar_v1_utc_overrides` (перевірити актуальність і наповнення).
- `docs/audit_v7_runtime_core.md` потребує узгодження формулювань із фактичними SSOT даними (closed_intervals уже наповнені).

### Продуктивність `closed_intervals_utc` зараз O(n) на кожен `is_open`

`TradingCalendar._is_closed_interval(ts_ms)` проходить `closed_intervals_utc` лінійно.
Для десятків інтервалів це ок, але якщо SSOT стане багаторічним (сотні/тисячі інтервалів) і `is_open` викликається на кожен tick/loop — це може стати небажаним CPU‑шумом. Це не критично для 12 інтервалів, але це “growth risk”.

## Висновок щодо виконання P7 і доказовість Acceptance Criteria

### Чи прибраний stub‑календар і чи календар став SSOT‑придатним

По фактичному `main`:

- **Stub‑календар як runtime‑механізм прибрано**: немає жодного модуля з stub‑календарем у `core/time/*`, а історичні згадки очищено.
- **SSOT дані календаря існують і використовуються**: `Calendar` читає `config/calendar_overrides.json` через loader, валідатор enforce‑ить ключі та TZ, `closed_intervals_utc` нормалізується й перевіряється рейками.
- **Без silent fallback** реалізовано як “degraded‑but‑loud”: `init_error` → `calendar_error` у degraded + error‑record у `errors[]`, при цьому market_state дає safe‑closed і валідний payload.

### Що з acceptance criteria по суті

- `status.snapshot.degraded` не містить stub‑тегів: у runtime/status деградація календаря — це `calendar_error`; stub‑тегів у runtime‑коді немає.
- `gate_closed_intervals → OK`: gate існує, включений у дефолтний manifest, і має явний unit‑тест на PASS.
- `gate_schedule_drift → OK`: gate існує й включений у manifest; перевірювані ним семантики покриті календарними тестами.

### Що я б зафіксував як “done”, а що — як “ще болить”

P7 як “прибрати stub і зробити SSOT‑календар з рейками/гейтами” **в коді виконано**: є SSOT JSON, є нормалізація, є деградація без silent fallback, є gates + tests.

“Прод‑придатність календаря” у runtime‑циклі FXCM узгоджена з SSOT (paused_market_closed використовує `calendar.next_open_ms`). Залишкові ризики — у даних/документації, а не в логіці.# P7 Calendar SSOT

## P7 Calendar SSOT у `Std07-1/fxcm_connector_v2`: глибинний аудит реалізації, рейок і залишкових ризиків

## Контекст P7 і що саме потрібно довести

У дорожній карті (Audit v7_1a) P7 визначено як заміну stub‑календаря на **реальний SSOT‑календар**, де:
- `is_open`, `next_open_utc`, `next_pause_utc` працюють коректно,
- `closed_intervals` беруться з SSOT‑даних (JSON),
- додані гейти `schedule_drift` та `closed_intervals` validity,
- відсутній silent fallback: невалідний календар має бути “loud” через `errors[]` + `degraded[]` або hard‑fail.

Acceptance criteria в тому ж документі формально зводяться до трьох тверджень: `status.snapshot.degraded` не містить stub‑тегів, гейти для closed intervals і schedule drift дають `OK`.

Нижче — перевірка по **фактичному коду `main`**, зі зв’язуванням “що є” ↔ “що вимагалось”, плюс список ризиків, які **вже не про stub**, але напряму впливають на “прод‑придатність календаря”.

## Реалізація SSOT‑календаря в `core/time/*`

### Де SSOT і як він підтягується

SSOT для календарних правил у репозиторії реалізовано як JSON‑профілі в `config/calendar_overrides.json` з ключем `calendar_tag` (наразі два профілі).

Клас `Calendar` (`core/time/calendar.py`) **на старті завжди** намагається завантажити overrides з `config/calendar_overrides.json` через `load_calendar_overrides(...)` і `calendar_tag`. Будь‑яка помилка парсингу/валідації вважається `init_error`. fileciteturn7file0turn8file0

Критично важливий rail: якщо в `Calendar` хтось спробує передати `closed_intervals_utc` напряму (не порожній список) — це **не “fallback”**, а ініціалізаційна помилка з явним повідомленням, що SSOT — тільки JSON.

Це прямо закриває вимогу “SSOT лише в даних” і “без silent fallback”: ін’єкція інтервалів ззовні не приймається тихо, вона ламає календар у стан `init_error`. fileciteturn7file0turn31file0

### Формат і рейки `closed_intervals_utc`

Нормалізація/валідація `closed_intervals_utc` централізована в `core/time/closed_intervals.py` функцією `normalize_closed_intervals_utc(...)`. Вона enforce‑ить:
- тип “список списків/кортежів”,
- рівно два елементи на інтервал,
- `start_ms` і `end_ms` — `int` (не `bool`),
- межі epoch rails через `MIN_EPOCH_MS/MAX_EPOCH_MS`,
- `start_ms < end_ms`,
- сортування за `start_ms`,
- відсутність overlap (`cur.start < prev.end` → помилка). fileciteturn9file0turn40file0

Це практично повний збіг з P7‑інваріантами “відсортовані, не перекриваються, start<end, UTC(epoch ms)”. fileciteturn33file0turn9file0

### Сесійна семантика `is_open/next_open/next_pause`

Вся семантика сесій реалізована у `TradingCalendar` (`core/time/sessions.py`):
- `is_trading_time(ts_ms)` повертає `False` якщо `init_error` або час попадає у `closed_intervals_utc`, у weekend close, або у daily break (для Mon‑Thu).
- `next_trading_open_ms(ts_ms)` знаходить наступний старт торгового інтервалу, враховуючи daily break і weekend boundary, а також “перестрибує” через `closed_intervals_utc` (якщо candidate попадає в closed interval, рекурсивно шукає далі).
- `next_trading_pause_ms(ts_ms)` повертає найближчу паузу (кінець поточного open‑інтервалу), але додатково вміє виявляти `closed_intervals_utc`, що починаються всередині open‑інтервалу, і тоді pause стає стартом такого closed interval.
- `market_state(ts_ms)` віддає `is_open`, `next_open_utc`, `next_pause_utc`, `calendar_tag`, `tz_backend`. fileciteturn8file0turn34file0

`Calendar.market_state(...)` делегує у `TradingCalendar.market_state(...)`, але якщо є `init_error`, то повертає “safe‑closed” з `tz_backend="init_error"` і `next_open_utc/next_pause_utc` виставленими в поточний UTC‑ISO (щоб payload завжди був валідний і не ламав status). fileciteturn7file0turn34file0

Окремо важливо: `Calendar.is_open/next_open_ms/next_pause_ms` при `init_error` повертають safe‑опції (False або поточний `ts_ms`). Це узгоджується з “degraded‑but‑loud”, а не з “тихою підміною” якихось правил. fileciteturn7file0turn31file0

### Які саме профілі є в SSOT зараз

`config/calendar_overrides.json` містить два профілі:
- `fxcm_calendar_v1_ny`: `tz_name="America/New_York"`, weekly open/close 17:00, daily break 17:00 на 5 хв, **є** `closed_intervals_utc` (epoch ms) + `holiday_policy` (required + min_future_days).
- `fxcm_calendar_v1_utc_overrides`: `tz_name="UTC"`, weekly open 23:01, weekly close 21:45, daily break 22:00 на 61 хв, **є** `closed_intervals_utc` (epoch ms) + `holiday_policy` (required + min_future_days). fileciteturn10file0turn45file0turn44file0

Факт міграції підтверджується наявністю `tools/migrate_v1_calendar_overrides.py`, який читає v1 формат (ISO `start/end` + `holidays`) і записує нормалізований список в `fxcm_calendar_v1_utc_overrides` у `calendar_overrides.json`. fileciteturn44file0turn45file0

“Прод‑придатність календаря” у runtime‑циклі FXCM тепер узгоджена з SSOT (paused_market_closed використовує `calendar.next_open_ms`). Залишкові ризики — у даних/документації (повнота `closed_intervals_utc` та актуальність доків), а не в логіці.
Ключовий нюанс (важливо для інтерпретації “drift”): gate **не порівнює** календар із якимось “еталоном поза SSOT” (наприклад, з FXCM‑розкладом або зашитими константами). Він фактично ловить:
- відрив реалізації `Calendar/TradingCalendar` від SSOT overrides (якщо код перестане читати JSON або почне інтерпретувати час неправильно),
- проблеми TZ‑резолву/конвертації (зсуви через tz backend),
- регресії у правилах break/week boundary.

Тобто gate — це **регресійний “drift від SSOT”**, а не “drift від реального ринку”. Це відповідає формулюванню P7 “drift без явного апдейту” у сенсі: код не має “дрейфувати” від SSOT непомітно. fileciteturn13file0turn33file0turn7file0

### Включення гейтів у дефолтний manifest

У `tools/exit_gates/manifest.json` гейти `gate_calendar_closed_intervals` та `gate_calendar_schedule_drift` входять у дефолтний набір.

Це підкріплено тестом `tests/test_manifest_includes_calendar_gates.py`, який перевіряє, що обидва ID є у manifest. fileciteturn29file0turn11file0

### Календарні тести: що покрито реально

Є два “шари” тестів:

1) **Тести на завантаження SSOT overrides**: `test_calendar_overrides_loading_for_tags` гарантує, що обидва профілі зчитуються і мають очікувані атрибути (TZ, daily_break_minutes). fileciteturn22file0turn8file0turn10file0

2) **Тести на семантику сесій/меж**:
- `tests/test_calendar_sessions.py` перевіряє:
  - `next_pause_ms` на межі daily break,
  - `next_open_ms` після break,
  - weekend boundary,
  - DST boundary (pre/post DST Sunday open дає різний UTC час). fileciteturn52file0turn8file0
- `tests/test_calendar_schedule_semantics.py` параметризовано перевіряє open/close/break для обох профілів (NY і UTC overrides), і окремо тестує `Calendar` з tmp overrides файлом (тобто шлях `overrides_path` працює). fileciteturn23file0turn7file0turn8file0
- `tests/test_calendar_closed_interval_effect.py` перевіряє, що `closed_intervals_utc` реально блокує trading_time. fileciteturn24file0turn8file0
- `tests/test_calendar_xau_profile.py` фіксує очікуване `next_open_ms` = 23:01 UTC для `fxcm_calendar_v1_utc_overrides` (weekend reopen і reopen після daily break). fileciteturn25file0turn10file0turn8file0
- Є окремі тести на `tz_backend` fallback (zoneinfo → dateutil → unknown). fileciteturn36file0turn8file0

У сумі це означає: вимога “коректні `is_open`, `next_open`, `next_pause`” не просто задекларована, а **закрита тестами на boundary‑сценарії**, включно з DST для NY профілю. fileciteturn52file0turn23file0turn36file0

## Surfacing у runtime: як виглядає “degraded‑but‑loud” на практиці

### Status snapshot більше не має stub‑тегів як деградації

У `runtime/status.py` деградація календаря робиться через тег `calendar_error`:
- `StatusManager._ensure_calendar_health()` перевіряє `calendar.health_error()` і якщо він є, додає `"calendar_error"` у `degraded` і додає error‑об’єкт з `code="calendar_error"`. fileciteturn14file0turn7file0
- `build_initial_snapshot()` робить те ж саме при старті (щоб вже перший snapshot був “loud”, якщо календар невалідний).

У самому репозиторії згадки stub‑календаря лишаються лише в історичних артефактах; у runtime‑коді їх немає.  
Тобто в “живому runtime” (модулі, які імпортуються й виконуються) stub‑тегів деградації **немає**. fileciteturn15file0turn15file4turn14file0turn39file0

Це рівно закриває acceptance criteria “`status.snapshot.degraded` НЕ містить stub‑тегів” — принаймні на рівні коду, який формує degraded‑теги. fileciteturn33file0turn14file0

### Як календар врізається в runtime‑composition

`app/composition.py` створює `Calendar` під runtime як `Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)`. fileciteturn42file0turn7file0

Тут важливий практичний наслідок рейки “SSOT лише JSON”: будь‑які спроби ін’єкції closed‑інтервалів поза `calendar_overrides.json` блокуються через `init_error`, а status автоматично стає `calendar_error` (degraded + errors[]).

### Де календар критично впливає на поведінку системи

Календар використовується не лише для “гарного status”, а як реальний rail:
- `runtime/history_provider.guard_history_ready()` пише в status `next_trading_open_ms` через `calendar.next_open_ms(...)`, тобто backoff/readiness логіка історії прямо залежить від календаря. fileciteturn21file0turn7file0
- `runtime/tail_guard.py` використовує `calendar.is_open(...)` при пошуку missing ranges (не рахувати дірки в hours/days коли ринок закритий), а також “repair дозволено лише коли ринок закритий” через `calendar.is_repair_window(...)`. fileciteturn55file0turn7file0

Це підсилює вимогу P7 “без silent fallback”: якщо календар “бреше”, він створює хвилю вторинних дефектів (неправильні gaps, неправильна відкладена репарація, тощо). fileciteturn55file0turn31file0

## Залишкові ризики і “тонкі місця” після виконання P7

### Критичний роз’їзд SSOT: FXCM stream ігнорував календар при паузі “market closed” (закрито)

Раніше у `runtime/fxcm_forexconnect.py` для `paused_market_closed` використовувався шлях через `closed_intervals_utc`, що міг не збігатися з SSOT календарем і провокував polling‑поведінку.

Поточний стан: у режимі `paused_market_closed` FXCM stream бере `next_open_ms` напряму з `calendar.next_open_ms(now_ms)`, тобто від SSOT‑календаря. Це знімає роз’їзд між runtime і SSOT у ключовій точці паузи. fileciteturn19file0turn7file0

### Дублювання джерел `closed_intervals_utc` у Config (закрито)

Поле `closed_intervals_utc` прибрано з `config/config.py`, а FXCM stream використовує SSOT календар напряму. Це усунуло дублювання джерел даних і “toxic” канал ін’єкції для Calendar.

### Документація частково не встигає за фактичним станом даних

`docs/calendar_sessions_spec.md` декларує, що правила recurrence беруться з SSOT у `config/calendar_overrides.json` і що `closed_intervals_utc` — allowlist жорстких закриттів. Це відповідає реалізації. fileciteturn31file0turn7file0turn8file0

Але TODO “додати святкові closed_intervals_utc для fxcm_calendar_v1_utc_overrides” тепер застарів (інтервали вже присутні в SSOT). Потрібно оновити текст документа, щоб не вводити в оману. fileciteturn31file0turn10file0turn45file0turn44file0

Окремо `docs/audit_v7_runtime_core.md` (дата 2026‑01‑27) каже “Calendar closed_intervals_utc: зараз порожні” і що v1 UTC‑оверрайди не перенесені. Але в актуальному `config/calendar_overrides.json` v1 UTC overrides профіль існує і має non‑empty `closed_intervals_utc`. fileciteturn32file0turn10file0turn45file0

Це не “баг”, але це ризик операційно: люди будуть приймати рішення, читаючи доки, які описують попередній стан або інший профіль (NY vs UTC overrides).

### Продуктивність `closed_intervals_utc` зараз O(n) на кожен `is_open`

`TradingCalendar._is_closed_interval(ts_ms)` проходить `closed_intervals_utc` лінійно.
Для десятків інтервалів це ок, але якщо SSOT стане багаторічним (сотні/тисячі інтервалів) і `is_open` викликається на кожен tick/loop — це може стати небажаним CPU‑шумом. Це не критично для 12 інтервалів, але це “growth risk”.

## Висновок щодо виконання P7 і доказовість Acceptance Criteria

### Чи прибраний stub‑календар і чи календар став SSOT‑придатним

По фактичному `main`:

- **Stub‑календар як runtime‑механізм прибрано**: немає жодного модуля з stub‑календарем у `core/time/*`, а історичні згадки очищено. fileciteturn7file0turn39file0
- **SSOT дані календаря існують і використовуються**: `Calendar` читає `config/calendar_overrides.json` через loader, валідатор enforce‑ить ключі та TZ, `closed_intervals_utc` нормалізується й перевіряється рейками. fileciteturn7file0turn8file0turn10file0turn9file0
- **Без silent fallback** реалізовано як “degraded‑but‑loud”: `init_error` → `calendar_error` у degraded + error‑record у `errors[]`, при цьому market_state дає safe‑closed і валідний payload. fileciteturn14file0turn7file0turn31file0turn34file0

### Що з acceptance criteria по суті

- `status.snapshot.degraded` не містить stub‑тегів: у runtime/status деградація календаря — це `calendar_error`; stub‑тегів у runtime‑коді немає. fileciteturn14file0turn39file0
- `gate_closed_intervals → OK`: gate існує, включений у дефолтний manifest, і має явний unit‑тест на PASS. fileciteturn12file0turn11file0turn27file0turn29file0
- `gate_schedule_drift → OK`: gate існує й включений у manifest; прямого unit‑тесту “PASS” я не бачу, але перевірювані ним семантики покриті календарними тестами (daily break / weekly boundary / профілі). fileciteturn13file0turn11file0turn52file0turn23file0

Як додатковий доказ (поза GitHub‑кодом), у наданому вами робочому журналі згадується, що `pytest` і `tools.run_exit_gates` запускались і завершувались з `EXIT_CODE=0`, а артефакти лежать в `reports/audit_p7_calendar_ssot/...`.
Це підкріплює “гейти OK” історично, але ці артефакти не присутні в repo‑tree `main` (ймовірно, це локальні/ігноровані файли). fileciteturn1file14turn11file0

### Що я б зафіксував як “done”, а що — як “ще болить”

P7 як “прибрати stub і зробити SSOT‑календар з рейками/гейтами” **в коді виконано**: є SSOT JSON, є нормалізація, є деградація без silent fallback, є gates + tests.

“Прод‑придатність календаря” у runtime‑циклі FXCM тепер узгоджена з SSOT (paused_market_closed використовує `calendar.next_open_ms`). Залишкові ризики — у даних/документації (повнота `closed_intervals_utc` та актуальність доків), а не в логіці.# P7 Calendar SSOT

## P7 Calendar SSOT у `Std07-1/fxcm_connector_v2`: глибинний аудит реалізації, рейок і залишкових ризиків

## Контекст P7 і що саме потрібно довести

У дорожній карті (Audit v7_1a) P7 визначено як заміну stub‑календаря на **реальний SSOT‑календар**, де:
- `is_open`, `next_open_utc`, `next_pause_utc` працюють коректно,
- `closed_intervals` беруться з SSOT‑даних (JSON),
- додані гейти `schedule_drift` та `closed_intervals` validity,
- відсутній silent fallback: невалідний календар має бути “loud” через `errors[]` + `degraded[]` або hard‑fail.

Acceptance criteria в тому ж документі формально зводяться до трьох тверджень: `status.snapshot.degraded` не містить stub‑тегів, гейти для closed intervals і schedule drift дають `OK`.

Нижче — перевірка по **фактичному коду `main`**, зі зв’язуванням “що є” ↔ “що вимагалось”, плюс список ризиків, які **вже не про stub**, але напряму впливають на “прод‑придатність календаря”.

## Реалізація SSOT‑календаря в `core/time/*`

### Де SSOT і як він підтягується

SSOT для календарних правил у репозиторії реалізовано як JSON‑профілі в `config/calendar_overrides.json` з ключем `calendar_tag` (наразі два профілі). fileciteturn10file0

Клас `Calendar` (`core/time/calendar.py`) **на старті завжди** намагається завантажити overrides з `config/calendar_overrides.json` через `load_calendar_overrides(...)` і `calendar_tag`. Будь‑яка помилка парсингу/валідації вважається `init_error`. fileciteturn7file0turn8file0

Критично важливий rail: якщо в `Calendar` хтось спробує передати `closed_intervals_utc` напряму (не порожній список) — це **не “fallback”**, а ініціалізаційна помилка з явним повідомленням, що SSOT — тільки JSON. fileciteturn7file0

Це прямо закриває вимогу “SSOT лише в даних” і “без silent fallback”: ін’єкція інтервалів ззовні не приймається тихо, вона ламає календар у стан `init_error`. fileciteturn7file0turn31file0

### Формат і рейки `closed_intervals_utc`

Нормалізація/валідація `closed_intervals_utc` централізована в `core/time/closed_intervals.py` функцією `normalize_closed_intervals_utc(...)`. Вона enforce‑ить:
- тип “список списків/кортежів”,
- рівно два елементи на інтервал,
- `start_ms` і `end_ms` — `int` (не `bool`),
- межі epoch rails через `MIN_EPOCH_MS/MAX_EPOCH_MS`,
- `start_ms < end_ms`,
- сортування за `start_ms`,
- відсутність overlap (`cur.start < prev.end` → помилка). fileciteturn9file0turn40file0

Це практично повний збіг з P7‑інваріантами “відсортовані, не перекриваються, start<end, UTC(epoch ms)”. fileciteturn33file0turn9file0

### Сесійна семантика `is_open/next_open/next_pause`

Вся семантика сесій реалізована у `TradingCalendar` (`core/time/sessions.py`):
- `is_trading_time(ts_ms)` повертає `False` якщо `init_error` або час попадає у `closed_intervals_utc`, у weekend close, або у daily break (для Mon‑Thu). fileciteturn8file0
- `next_trading_open_ms(ts_ms)` знаходить наступний старт торгового інтервалу, враховуючи daily break і weekend boundary, а також “перестрибує” через `closed_intervals_utc` (якщо candidate попадає в closed interval, рекурсивно шукає далі). fileciteturn8file0
- `next_trading_pause_ms(ts_ms)` повертає найближчу паузу (кінець поточного open‑інтервалу), але додатково вміє виявляти `closed_intervals_utc`, що починаються всередині open‑інтервалу, і тоді pause стає стартом такого closed interval. fileciteturn8file0
- `market_state(ts_ms)` віддає `is_open`, `next_open_utc`, `next_pause_utc`, `calendar_tag`, `tz_backend`. fileciteturn8file0turn34file0

`Calendar.market_state(...)` делегує у `TradingCalendar.market_state(...)`, але якщо є `init_error`, то повертає “safe‑closed” з `tz_backend="init_error"` і `next_open_utc/next_pause_utc` виставленими в поточний UTC‑ISO (щоб payload завжди був валідний і не ламав status). fileciteturn7file0turn34file0

Окремо важливо: `Calendar.is_open/next_open_ms/next_pause_ms` при `init_error` повертають safe‑опції (False або поточний `ts_ms`). Це узгоджується з “degraded‑but‑loud”, а не з “тихою підміною” якихось правил. fileciteturn7file0turn31file0

### Які саме профілі є в SSOT зараз

`config/calendar_overrides.json` містить два профілі:
- `fxcm_calendar_v1_ny`: `tz_name="America/New_York"`, weekly open/close 17:00, daily break 17:00 на 5 хв, `closed_intervals_utc=[]`. fileciteturn10file0
- `fxcm_calendar_v1_utc_overrides`: `tz_name="UTC"`, weekly open 23:01, weekly close 21:45, daily break 22:00 на 61 хв, і **12** `closed_intervals_utc` (epoch ms), що виглядають як міграція “v1 holidays + explicit intervals”. fileciteturn10file0turn45file0turn44file0

Факт міграції підтверджується наявністю `tools/migrate_v1_calendar_overrides.py`, який читає v1 формат (ISO `start/end` + `holidays`) і записує нормалізований список в `fxcm_calendar_v1_utc_overrides` у `calendar_overrides.json`. fileciteturn44file0turn45file0

## Exit gates і тестове покриття: що реально зафіксовано

### Gate для валідності `calendar_overrides.json` і `closed_intervals_utc`

`gate_calendar_closed_intervals`:
- читає `config/calendar_overrides.json`,
- перевіряє, що це список профілів,
- enforce‑ить ключі schedule (`weekly_open/weekly_close/daily_break_start/daily_break_minutes/tz_name`) і значення (HH:MM, int>0, TZ резолвиться),
- проганяє `normalize_closed_intervals_utc(...)` для `closed_intervals_utc` кожного профілю. fileciteturn12file0turn9file0turn8file0

Є окремий unit‑тест `tests/test_gate_calendar_closed_intervals.py`, який очікує `ok is True`. Це сильний сигнал, що на `main` gate не просто існує, а й має PASS‑трек у тестах. fileciteturn27file0turn12file0

### Gate для “schedule drift” і що він насправді ловить

`gate_calendar_schedule_drift`:
- завантажує runtime config (`load_config()`),
- створює `Calendar([], config.calendar_tag)` і фейлить, якщо календар має `init_error`,
- паралельно вантажить overrides для того ж `calendar_tag`,
- перевіряє, що:
  - за хвилину до daily break календар OPEN,
  - через хвилину після старту break — CLOSED,
  - через хвилину після weekly close — CLOSED,
  - через хвилину після weekly open — OPEN. fileciteturn13file0turn7file0turn8file0turn20file0

Ключовий нюанс (важливо для інтерпретації “drift”): gate **не порівнює** календар із якимось “еталоном поза SSOT” (наприклад, з FXCM‑розкладом або зашитими константами). Він фактично ловить:
- відрив реалізації `Calendar/TradingCalendar` від SSOT overrides (якщо код перестане читати JSON або почне інтерпретувати час неправильно),
- проблеми TZ‑резолву/конвертації (зсуви через tz backend),
- регресії у правилах break/week boundary.

Тобто gate — це **регресійний “drift від SSOT”**, а не “drift від реального ринку”. Це відповідає формулюванню P7 “drift без явного апдейту” у сенсі: код не має “дрейфувати” від SSOT непомітно. fileciteturn13file0turn33file0turn7file0

### Включення гейтів у дефолтний manifest

У `tools/exit_gates/manifest.json` гейти `gate_calendar_closed_intervals` та `gate_calendar_schedule_drift` входять у дефолтний набір. fileciteturn11file0

Це підкріплено тестом `tests/test_manifest_includes_calendar_gates.py`, який перевіряє, що обидва ID є у manifest. fileciteturn29file0turn11file0

### Календарні тести: що покрито реально

Є два “шари” тестів:

1) **Тести на завантаження SSOT overrides**: `test_calendar_overrides_loading_for_tags` гарантує, що обидва профілі зчитуються і мають очікувані атрибути (TZ, daily_break_minutes). fileciteturn22file0turn8file0turn10file0

2) **Тести на семантику сесій/меж**:
- `tests/test_calendar_sessions.py` перевіряє:
  - `next_pause_ms` на межі daily break,
  - `next_open_ms` після break,
  - weekend boundary,
  - DST boundary (pre/post DST Sunday open дає різний UTC час). fileciteturn52file0turn8file0
- `tests/test_calendar_schedule_semantics.py` параметризовано перевіряє open/close/break для обох профілів (NY і UTC overrides), і окремо тестує `Calendar` з tmp overrides файлом (тобто шлях `overrides_path` працює). fileciteturn23file0turn7file0turn8file0
- `tests/test_calendar_closed_interval_effect.py` перевіряє, що `closed_intervals_utc` реально блокує trading_time. fileciteturn24file0turn8file0
- `tests/test_calendar_xau_profile.py` фіксує очікуване `next_open_ms` = 23:01 UTC для `fxcm_calendar_v1_utc_overrides` (weekend reopen і reopen після daily break). fileciteturn25file0turn10file0turn8file0
- Є окремі тести на `tz_backend` fallback (zoneinfo → dateutil → unknown). fileciteturn36file0turn8file0

У сумі це означає: вимога “коректні `is_open`, `next_open`, `next_pause`” не просто задекларована, а **закрита тестами на boundary‑сценарії**, включно з DST для NY профілю. fileciteturn52file0turn23file0turn36file0

## Surfacing у runtime: як виглядає “degraded‑but‑loud” на практиці

### Status snapshot більше не має stub‑тегів як деградації

У `runtime/status.py` деградація календаря робиться через тег `calendar_error`:
- `StatusManager._ensure_calendar_health()` перевіряє `calendar.health_error()` і якщо він є, додає `"calendar_error"` у `degraded` і додає error‑об’єкт з `code="calendar_error"`. fileciteturn14file0turn7file0
- `build_initial_snapshot()` робить те ж саме при старті (щоб вже перший snapshot був “loud”, якщо календар невалідний). fileciteturn14file0

У самому репозиторії згадки stub‑календаря лишаються лише в історичних артефактах; у runtime‑коді їх немає.  
Тобто в “живому runtime” (модулі, які імпортуються й виконуються) stub‑тегів деградації **немає**. fileciteturn15file0turn15file4turn14file0turn39file0

Це рівно закриває acceptance criteria “`status.snapshot.degraded` НЕ містить stub‑тегів” — принаймні на рівні коду, який формує degraded‑теги. fileciteturn33file0turn14file0

### Як календар врізається в runtime‑composition

`app/composition.py` створює `Calendar` під runtime як `Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)`. fileciteturn42file0turn7file0

Тут важливий практичний наслідок рейки “SSOT лише JSON”: будь‑які спроби ін’єкції closed‑інтервалів поза `calendar_overrides.json` блокуються через `init_error`, а status автоматично стає `calendar_error` (degraded + errors[]).

### Де календар критично впливає на поведінку системи

Календар використовується не лише для “гарного status”, а як реальний rail:
- `runtime/history_provider.guard_history_ready()` пише в status `next_trading_open_ms` через `calendar.next_open_ms(...)`, тобто backoff/readiness логіка історії прямо залежить від календаря. fileciteturn21file0turn7file0
- `runtime/tail_guard.py` використовує `calendar.is_open(...)` при пошуку missing ranges (не рахувати дірки в hours/days коли ринок закритий), а також “repair дозволено лише коли ринок закритий” через `calendar.is_repair_window(...)`. fileciteturn55file0turn7file0

Це підсилює вимогу P7 “без silent fallback”: якщо календар “бреше”, він створює хвилю вторинних дефектів (неправильні gaps, неправильна відкладена репарація, тощо). fileciteturn55file0turn31file0

## Залишкові ризики і “тонкі місця” після виконання P7

### Критичний роз’їзд SSOT: FXCM stream ігнорував календар при паузі “market closed” (виправлено)

Найбільш небезпечний роз’їзд у поточному `main`:

У `runtime/fxcm_forexconnect.py` в режимі `paused_market_closed` наступний retry час рахується так:
- якщо `status.calendar.is_open(now_ms)` == False → береться `next_open_ms = _next_open_ms(now_ms, self.config.closed_intervals_utc)`, а **не** `calendar.next_open_ms(now_ms)`. fileciteturn19file0turn7file0turn20file0
- `_next_open_ms` шукає лише “кінець closed interval, який містить now”; якщо список порожній — повертає `now_ms`. fileciteturn19file0turn20file0

Але `Config.closed_intervals_utc` за замовчуванням порожній. fileciteturn20file0

Результат: навіть якщо календар (SSOT overrides) правильно каже “ринок закритий” на weekend/daily break, FXCM stream не отримує “справжній next_open” від календаря і буде прокидатися по backoff‑таймеру (фактично polling), а не спати “до відкриття ринку”. fileciteturn19file0turn20file0turn8file0

Це **не ламає P7 формально** (бо FXCM інтеграція була non‑goal), але ламає “прод‑придатність календаря” в сенсі операційної поведінки: календар є, але його `next_open_ms` не використовується в ключовій точці “паузи до open”. fileciteturn33file0turn19file0turn21file0

### Дублювання джерел `closed_intervals_utc` у Config ще існує, але для Calendar воно “toxic”

В `config/config.py` поле `closed_intervals_utc` лишилось як частина SSOT конфігу. fileciteturn20file0  
Водночас `Calendar` трактує непорожнє значення як `init_error` (тобто його не можна використовувати як альтернативний SSOT). fileciteturn7file0

Отже, зараз існує “пастка”:
- `Config.closed_intervals_utc` **ще живе** та використовується у FXCM stream (для retry), fileciteturn19file0turn20file0
- але для Calendar це “заборонений канал ін’єкції” (ініціалізаційна помилка). fileciteturn7file0

Це класичний SSOT‑smell: два канали даних про одне й те саме, але з протилежною семантикою (“можна” vs “не можна”). Якщо лишити як є — ризик регресій і непередбачуваних “calendar_error” після конфіг‑змін.

### Документація частково не встигає за фактичним станом даних

`docs/calendar_sessions_spec.md` декларує, що правила recurrence беруться з SSOT у `config/calendar_overrides.json` і що `closed_intervals_utc` — allowlist жорстких закриттів. Це відповідає реалізації. fileciteturn31file0turn7file0turn8file0

Але там є TODO “додати святкові closed_intervals_utc для fxcm_calendar_v1_utc_overrides”. При цьому в `config/calendar_overrides.json` уже є 12 інтервалів, що виглядають як результат міграції “holidays + explicit intervals” з v1 evidence. fileciteturn31file0turn10file0turn45file0turn44file0

Окремо `docs/audit_v7_runtime_core.md` (дата 2026‑01‑27) каже “Calendar closed_intervals_utc: зараз порожні” і що v1 UTC‑оверрайди не перенесені. Але в актуальному `config/calendar_overrides.json` v1 UTC overrides профіль існує і має non‑empty `closed_intervals_utc`. fileciteturn32file0turn10file0turn45file0

Це не “баг”, але це ризик операційно: люди будуть приймати рішення, читаючи доки, які описують попередній стан або інший профіль (NY vs UTC overrides).

### Продуктивність `closed_intervals_utc` зараз O(n) на кожен `is_open`

`TradingCalendar._is_closed_interval(ts_ms)` проходить `closed_intervals_utc` лінійно. fileciteturn8file0  
Для десятків інтервалів це ок, але якщо SSOT стане багаторічним (сотні/тисячі інтервалів) і `is_open` викликається на кожен tick/loop — це може стати небажаним CPU‑шумом. Це не критично для 12 інтервалів, але це “growth risk”.

## Висновок щодо виконання P7 і доказовість Acceptance Criteria

### Чи прибраний stub‑календар і чи календар став SSOT‑придатним

По фактичному `main`:

- **Stub‑календар як runtime‑механізм прибрано**: немає жодного модуля з stub‑календарем у `core/time/*`, а історичні згадки очищено. fileciteturn7file0turn39file0
- **SSOT дані календаря існують і використовуються**: `Calendar` читає `config/calendar_overrides.json` через loader, валідатор enforce‑ить ключі та TZ, `closed_intervals_utc` нормалізується й перевіряється рейками. fileciteturn7file0turn8file0turn10file0turn9file0
- **Без silent fallback** реалізовано як “degraded‑but‑loud”: `init_error` → `calendar_error` у degraded + error‑record у `errors[]`, при цьому market_state дає safe‑closed і валідний payload. fileciteturn14file0turn7file0turn31file0turn34file0

### Що з acceptance criteria по суті

- `status.snapshot.degraded` не містить stub‑тегів: у runtime/status деградація календаря — це `calendar_error`; stub‑тегів у runtime‑коді немає. fileciteturn14file0turn39file0
- `gate_closed_intervals → OK`: gate існує, включений у дефолтний manifest, і має явний unit‑тест на PASS. fileciteturn12file0turn11file0turn27file0turn29file0
- `gate_schedule_drift → OK`: gate існує й включений у manifest; прямого unit‑тесту “PASS” я не бачу, але перевірювані ним семантики покриті календарними тестами (daily break / weekly boundary / профілі). fileciteturn13file0turn11file0turn52file0turn23file0

Як додатковий доказ (поза GitHub‑кодом), у наданому вами робочому журналі згадується, що `pytest` і `tools.run_exit_gates` запускались і завершувались з `EXIT_CODE=0`, а артефакти лежать в `reports/audit_p7_calendar_ssot/...`.
Це підкріплює “гейти OK” історично, але ці артефакти не присутні в repo‑tree `main` (ймовірно, це локальні/ігноровані файли). fileciteturn1file14turn11file0

### Що я б зафіксував як “done”, а що — як “ще болить”

P7 як “прибрати stub і зробити SSOT‑календар з рейками/гейтами” **в коді виконано**: є SSOT JSON, є нормалізація, є деградація без silent fallback, є gates + tests.

Але “прод‑придатність календаря” у реальному runtime‑циклі FXCM стріму **частково під питанням** через роз’їзд “calendar.next_open_ms” vs “config.closed_intervals_utc” у `paused_market_closed`. Це не P7‑scope формально, але це найбільший практичний хвіст після P7. fileciteturn19file0turn21file0turn7file0