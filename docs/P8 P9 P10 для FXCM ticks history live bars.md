# Connector_v2: read‑only розслідування коду P8/P9/P10 для FXCM (ticks, history, live bars)

## Рамки дослідження та джерела

Це розслідування виконане в режимі **read‑only discovery**: лише читання коду й документів, **без запуску тестів/exit‑gates/аудит‑сьютів** і без внесення змін у код. Факти фіксую як `path:Lx-Ly` (лінії з отриманих артефактів), а висновки позначаю як інтерпретації або ризики.

Основні вихідні вимоги/очікування для P8/P9/P10 описані в `docs/Audit v7_1a.md` (зокрема: P8 — real tick feed + rails; P9 — history provider 1m final; P10 — live finalization tick→1m з market‑aware/gap policy і “no silent repairs”). fileciteturn55file0L60-L143

Додатковий контекст по runtime/core (SSOT, rails, календар, “preview/final gap”, операційні ризики) зафіксований у `docs/audit_v7_runtime_core.md`. fileciteturn65file0L10-L112

Код аналізувався у репозиторії `Std07-1/fxcm_connector_v2` (фактичні файли й лінії наведено нижче), а також для порівняння формату даних FXCM history переглянуті тести у `Std07-1/ForexConnectAPI_v2.1` (саме як “еталон очікуваних ключів” для dict‑рядків history). fileciteturn58file0L23-L80

Важлива **розбіжність “док ↔ код”** (як сигнал ризику, не як помилка сама по собі):  
* `docs/Audit v7_1a.md` для P9 згадує `runtime/history_fxcm_provider.py` (та gate `gate_fxcm_history_smoke.py`), але в актуальному runtime реальна інтеграція зроблена в `runtime/fxcm/history_provider.py`, а `fxcm/history_fxcm_provider.py` — лише “скелет/заглушка”.
 fileciteturn55file0L90-L114 fileciteturn26file0L20-L75 fileciteturn31file0L11-L20  
* Для P10 docs очікують окремий `runtime/live_bar_builder.py` та `gate_live_final_invariants.py`, але в `tools/exit_gates/manifest.json` такого gate немає, і live finalization реалізована імпліцитно через “archive closed 1m preview → FileCache”.
fileciteturn55file0L117-L143 fileciteturn40file0L13-L35 fileciteturn19file0L495-L546

## Карта виконуваного пайплайна P8→P10

Нижче — фактичний ланцюжок даних, який зараз збирається з runtime (P8 tick stream) + preview builder (частина P10) + FileCache (SSOT для 1m, використовується warmup/backfill/tail_guard):

![Схема пайплайна P8→P10](sandbox:/mnt/data/connector_v2_p8_p9_p10_pipeline.png)

[Завантажити схему](sandbox:/mnt/data/connector_v2_p8_p9_p10_pipeline.png)

Ключові точки потоку:

`FxcmForexConnectStream` запускається лише якщо `ensure_fxcm_ready()` пройшов readiness‑перевірки (backend/secrets/SDK), і піднімає оффер‑підписку `FXCMOfferSubscription` (OFFERS table) з конвертацією row→tick через `_offer_row_to_tick()`.
fileciteturn66file0L65-L152 fileciteturn66file0L205-L241 fileciteturn66file0L279-L341

Далі tick “впадає” в `_handle_fxcm_tick()` у `app/composition.py`, де:
* (опційно) публікується tick у `{NS}:price_tik` через `TickPublisher.publish_tick()` (якщо `tick_mode == "fxcm"`); fileciteturn19file0L461-L473 fileciteturn24file0L20-L90  
* tick завжди йде в preview builder (`PreviewCandleBuilder` → `core.market.preview_builder.PreviewBuilder`) і при інтервалі публікуються preview payloads у `{NS}:ohlcv` як `complete=false`;
fileciteturn19file0L474-L492 fileciteturn20file0L13-L36 fileciteturn17file0L92-L182 fileciteturn53file0L58-L85  
* закриті 1m preview‑бари (все крім останнього “живого” бара) відбираються `select_closed_bars_for_archive()` і пишуться в `FileCache.append_complete_bars()` як `complete=True` із `source="stream_close"` (але source не зберігається в CSV‑схемі FileCache).
fileciteturn19file0L493-L546 fileciteturn20file0L38-L49 fileciteturn36file0L57-L88 fileciteturn37file0L103-L131

**Важливо:** публікація `complete=true` в `{NS}:ohlcv` зараз робиться лише “історичним” шляхом (`publish_ohlcv_final_1m`, `source="history"`) — переважно у warmup/backfill або republish, а не у live tick path. fileciteturn53file0L86-L114 fileciteturn19file0L206-L253

## P8 — FXCM Tick feed: факти, rails, liveness/reconnect, degrade‑loud

### Readiness/запуск стріму та loud‑помилки

Readiness розкладено на два кроки:

`check_fxcm_environment()` валідовує backend і залежності:  
* `fxcm_backend == "disabled"` → not ok;  
* `fxcm_backend == "replay"` → ok (особливий режим);  
* `fxcm_backend != "forexconnect"` → not supported;  
* відсутні `fxcm_username/fxcm_password` → not ok;  
* немає ForexConnect SDK → not ok. fileciteturn66file0L65-L77

`ensure_fxcm_ready()` пише у status “connected/disabled/error”, додає `errors[]` і `degraded[]` для критичних умов (secrets missing, sdk missing, backend not supported), і повертає bool, який блокує старт стріму. fileciteturn66file0L80-L152 fileciteturn66file0L382-L390

Ризик точності статусу: якщо `fxcm_backend == "replay"`, `check_fxcm_environment()` повертає `ok=True` і `ensure_fxcm_ready()` виставляє state `"connected"`, хоча це не реальний ForexConnect‑стрім (це може плутати спостережуваність/операційні дешборди). fileciteturn66file0L65-L91

### Нормалізація tick та “tick rails”

Таймстемп події tick (`tick_ts_ms`) береться **не** з wall‑clock: `_offer_row_to_tick()` шукає час у наборі кандидатів (`time`, `timestamp`, `event_ts`, `last_update_time`, …) і конвертує через `to_epoch_ms_utc()`. fileciteturn66file0L178-L202 fileciteturn66file0L205-L241

Якщо event time відсутній, tick **гучно відкидається**:  
* `errors[]`: `missing_tick_event_ts`,  
* інкрементується drop‑лічильник/вікно (`record_tick_drop_missing_event`),  
* метрика `fxcm_ticks_dropped_total{reason="missing_event_ts"}` (якщо metrics увімкнені). fileciteturn66file0L221-L233

Якщо в процесі конвертації row→tick з’являється `ContractError` (наприклад немає `instrument` або `bid/ask`), це теж деградує систему: `tick_contract_reject`, `degraded=tick_contract_reject`, інкременти contract‑reject лічильників. fileciteturn66file0L306-L323

На шарі публікації tick у Redis (`runtime/tick_feed.py`) є додатковий rail проти “out‑of‑order tick”: якщо `tick_ts_ms` менший за попередній `last_tick_ts_ms` у status, tick не публікується, ставиться `tick_out_of_order` + degraded, і піднімаються contract‑reject/drop лічильники.
fileciteturn24file0L39-L61

### Status rails: skew/lag та “preview pause” від деградації event time

`StatusManager.record_tick()` рахує:  
* `tick_skew_ms = snap_ts_ms - tick_ts_ms`; якщо skew негативний — фіксується помилка `tick_skew_negative`, ставиться degraded і skew примусово обнуляється; fileciteturn21file0L522-L543  
* `tick_lag_ms = now_ms - snap_ts_ms` (затримка обробки/публікації, а не мережевий lag від FXCM). fileciteturn21file0L540-L548

Окремо `record_tick_drop_missing_event()` веде 60‑секундне вікно seen/dropped і вмикає health‑rail: якщо drop_rate ≥ 0.5, система ставить degraded `tick_event_time_unavailable` і **паузить preview** (`_preview_paused=True`);
якщо drop_rate ≤ 0.1 — деградація знімається й preview розпаузується.
fileciteturn21file0L558-L599

Це прямо відповідає “degrade‑loud” і “fail‑fast”, але має наслідок: якщо FXCM часто не дає event time (реально або через parsing), превʼю може системно “впасти в паузу”.

### FSM + liveness/debounce: resubscribe → reconnect і що реально покривають гейти

FSM (“stale_no_ticks”) описаний в `runtime/fxcm/fsm.py`: при перевищенні `stale_s` FSM спершу віддає `action="resubscribe"` (з лімітом `resubscribe_retries`), далі `action="reconnect"` з експоненційним backoff. fileciteturn43file0L64-L95

`FxcmSessionManager.on_timer()` інтегрує FSM із календарем (`adapter.is_market_open(now_ms)`): коли ринок закритий — stale‑логіка не активується і `fxcm_stale_no_ticks` деградація очищається; коли відкритий — resubscribe/reconnect пробують відпрацювати. fileciteturn22file0L37-L65

`FxcmTickLiveness.check()` додає **cooldown‑debounce**: навіть якщо FSM просить reconnect, реальний “request_reconnect” блокується, доки не мине `cooldown_s` від попереднього reconnect‑request. fileciteturn23file0L21-L58

Поточний exit‑gate `gate_fxcm_tick_liveness.py` перевіряє **тільки** debounce‑логіку (очікує reconnect на “старому” tick і потім блок reconnect у cooldown). Це юніт‑перевірка, вона не перевіряє **факт реальних тіків, lag_ms або “ticks>0”**. fileciteturn25file0L10-L33

Це конфліктує з очікуванням P8 у `docs/Audit v7_1a.md`, де gate описаний як “ticks>0, lag sane” (тобто інтеграційний/смоук). fileciteturn55file0L62-L84

Окремо є gate, який прямо забороняє брати `tick_ts_ms` з wall‑clock (`time.time()`), скануючи `runtime/fxcm_forexconnect.py` на підозрілі патерни. fileciteturn61file0L10-L23

### Стан “market closed”: фактична поведінка і прихований роз’їзд із SSOT‑календарем

Коли календар каже “ринок закритий”, `FxcmForexConnectStream._run()` переходить у `state="paused_market_closed"`, підраховує `retry_ms` як `max(next_open_ms, now + backoff)` і засинає (реалізовано як цикл sleep по 0.5с з верхньою межею 30s на ітерацію). fileciteturn66file0L456-L478

Але `next_open_ms` береться через `_next_open_ms(now_ms, self.config.closed_intervals_utc)` (тобто з **config.closed_intervals_utc**). fileciteturn66file0L459-L471

Тут є структурний роз’їзд: `core.time.calendar.Calendar` явно вважає, що `closed_intervals_utc` **має бути порожнім у Calendar**, а SSOT для closed intervals — `config/calendar_overrides.json`;
якщо `closed_intervals_utc` передати непорожнім, Calendar ставить init‑error і `is_open()` завжди false.
fileciteturn67file0L34-L38 fileciteturn67file0L72-L76

Тобто у “правильній” конфігурації `config.closed_intervals_utc` буде порожнім, `_next_open_ms()` поверне `now_ms`, і “sleep до next open” фактично деградує до backoff‑петлі (без точного next_open від календаря).
Це підвищує ризик зайвого churn/yoyo‑reconnect у довгі вихідні/свята, і не відповідає “sleep до calendar.next_open_ms” як задуму P8. fileciteturn66file0L353-L357 fileciteturn67file0L89-L93

### Критичний concurrency‑ризик: shared `_stop_event` у dataclass

`FxcmForexConnectStream` оголошує `_stop_event: threading.Event = threading.Event()` як дефолтне значення поля dataclass. Це означає **один і той самий Event об’єкт на всі інстанси**, бо значення створюється на етапі визначення класу, а не через `default_factory`.
У сценаріях “дві копії стріму в одному процесі” це може призвести до взаємного “зупинив один — зупинив усіх”. fileciteturn66file0L373-L390

Це не обов’язково проявиться в нормальному runtime (де стрім зазвичай один), але як архітектурний rail проти дубль‑потоків це слабке місце.

## P9 — FXCM History Provider: fetch, chunking, budget/backoff, детермінізм

### Реальний провайдер історії і “заглушка”, яка може вводити в оману

Актуальний runtime‑провайдер: `runtime/fxcm/history_provider.py` (`FxcmHistoryProvider` + `FxcmForexConnectHistoryAdapter`). fileciteturn26file0L20-L75 fileciteturn26file0L143-L184

Файл `fxcm/history_fxcm_provider.py` — лише скелет, який завжди кидає RuntimeError (“FXCM провайдер не налаштований у P3…”). Якщо хтось випадково підключить/імпортує його як “provider=fxcm” в іншому місці, отримає loud fail. Це потенційний технічний борг/“artifact drift”. fileciteturn31file0L11-L20

### Readiness/backoff інтегровано через `guard_history_ready` і enforced gate

Контракт HistoryProvider (Protocol) включає `is_history_ready()`, `should_backoff()`, `note_not_ready()` і `fetch_1m_final()`. fileciteturn27file0L19-L29

`guard_history_ready()` робить:  
* читає `ready, reason = provider.is_history_ready()`;  
* дивиться `backoff_active = provider.should_backoff(now_ms)`;  
* якщо не ready — ставить `status.history` (retry_after/next_open/backoff), пише `errors[]` `fxcm_history_not_ready`, деградує `history_not_ready` (+ `history_backoff_active`), і кидає `HistoryNotReadyError`. fileciteturn27file0L41-L103

`run_warmup()` і `run_backfill()` викликають `guard_history_ready()` перед основним циклом fetch; це правильно “по рейках”, але означає, що readiness перевіряється **раз на команду/символ**, а не перед кожним чанком. fileciteturn28file0L32-L48 fileciteturn29file0L32-L48

Є exit‑gate, який статично сканує call‑sites і фейлить, якщо десь знайдено `fetch_1m_final`/`fetch_history` без `guard_history_ready`. Тобто “не готовий — не фетчимо” enforced як дисципліна. fileciteturn50file0L9-L30

### Budget: token bucket + global inflight

`HistoryBudget` реалізує token bucket (`capacity`, `refill_per_sec`) плюс **global inflight** і per‑symbol inflight. Фактично одночасно може бути лише **один** FXCM history request на весь процес (бо `_global_inflight` блокує інших). fileciteturn30file0L11-L55

Це безпечніше для FXCM rate limits, але операційно створює backpressure: при multi‑symbol warmup/backfill команди будуть серіалізовані.

### Парсинг рядків history: імовірний дефект із key‑case (“Date”)

`FxcmForexConnectHistoryAdapter.fetch_1m()` робить прямий `fx.get_history(instrument, "m1", start_dt, end_dt)` і передає результат у `_rows_to_bars(symbol, rows, limit)`. fileciteturn26file0L43-L66

`_rows_to_bars()` шукає `open_time_raw` в ключах `["open_time", "time", "timestamp", "date", "open_time_utc"]` і, якщо не знаходить/не конвертує — пропускає рядок. fileciteturn26file0L105-L118

У тестах/імітації з `Std07-1/ForexConnectAPI_v2.1` `FakeForexConnect.get_history()` повертає list[dict] з ключем **"Date"** (з великої літери), і саме по ньому робить маску часу. fileciteturn58file0L30-L34 fileciteturn58file0L52-L79

Отже, якщо реальний ForexConnect SDK (або його Python‑wrapper) повертає dict‑рядки з ключем `"Date"` (як у цьому POC/тестах), поточний `_rows_to_bars()` може **не побачити open_time**, відкинути рядки і повернути “0 барів”.
Це прямо узгоджується з ризиком, зафіксованим у `docs/audit_v7_runtime_core.md` (“FXCM history 0 bars”). fileciteturn26file0L105-L114 fileciteturn58file0L30-L34 fileciteturn65file0L88-L92

Це поки що **обґрунтована підозра**, а не доведений баг: у live SDK рядки можуть бути не dict, а об’єкти з атрибутом `time` (тоді все ок). Але у вас вже є “контр‑приклад” у другому репо, який показує реалістичний формат dict‑history з `"Date"`. fileciteturn58file0L23-L34

### Формування bar payload та інваріанти final 1m

Позитивне: `_rows_to_bars()` формує бари у канонічному вигляді `open_time_ms`, `close_time_ms`, `complete=1`, `synthetic=0`, `source="history"`, і `event_ts_ms == close_time_ms`.
Це відповідає інваріантам P9 для final 1m (принаймні на рівні структури). fileciteturn26file0L125-L140 fileciteturn55file0L102-L104

### Chunking: є, але семантика меж має “слизький” off‑by‑one/gap‑ризик

`FxcmHistoryProvider.fetch_1m_final()` робить chunking по `chunk_minutes` (плюс “probe_first” для великих діапазонів), ітеруючи `t` до `end_ms`. fileciteturn26file0L160-L179 fileciteturn26file0L207-L223

Критичний фрагмент:  
* `chunk_end = min(t + chunk_ms - 1, end_ms)`  
* після fetch: `t = chunk_end + 60_000` fileciteturn26file0L170-L179

Цей крок виглядає як мінімум **ризикований по інтервальній семантиці**: якщо `t` інтерпретується як open_time, то правильний наступний старт мав би бути `chunk_end + 1`, а не `+ 60_000` (інакше виникає “дірка” між чанками).
Якщо `t` інтерпретується як close_time, тоді `+60_000` логічний (це close наступної хвилини), але тоді `chunk_end` мав би бути `t + chunk_ms`, а не `t + chunk_ms - 1` (інакше накопичується drift на 1ms кожен чанк).
Сам код не документує явно, що таке `start_ms/end_ms` (open чи close‑орієнтовані межі), тому це — **технічний борг семантики** й джерело потенційної недетермінованості/прогалин. fileciteturn26file0L160-L179

Наслідок для P9 “determinism”: без чіткого, тестом зафіксованого контракту меж (`start_ms/end_ms`) два прогони однієї команди можуть давати різні “крайні” хвилини (особливо на межах day/weekend). У `docs/Audit v7_1a.md` determinism названий прямо як мета P9. fileciteturn55file0L90-L109

## P10 — Live Bar Builder: поточний стан, невідповідності вимогам “final”, gap policy

### Preview builder (реалізовано) і як саме воно працює

SSOT preview builder знаходиться в `core/market/preview_builder.py`:  
* `PreviewBuilder.on_tick()` на кожному tick ітерує `config.ohlcv_preview_tfs`, рахує `bucket_start` (для `1d` через trading_day_boundary_utc, для інших — через `tick_ts_ms // tf_ms * tf_ms`), і збирає `OhlcvBar` у памʼяті; fileciteturn17file0L103-L163  
* бари зберігаються в in‑memory `OhlcvCache` (deque), де update робить replace за `open_time`, інакше append; fileciteturn17file0L56-L72  
* у payload preview завжди `complete: False`, `source: "stream"`. fileciteturn17file0L165-L181

Preview‑обгортка `PreviewCandleBuilder` в runtime — thin wrapper над core PreviewBuilder. fileciteturn20file0L13-L36

### Публікація preview у Redis (є) і запис “закритих 1m” у FileCache (є)

У live tick handler (`app/composition.py::_handle_fxcm_tick`):  
* preview payloads публікуються через `publisher.publish_ohlcv_batch()` (який **жорстко ставить** `complete: False` і використовує `validate_ohlcv_preview_batch`). fileciteturn19file0L479-L492 fileciteturn53file0L58-L85  
* “закриті бари” відбираються як `bars[:-1]` в `select_closed_bars_for_archive()` та архівуються. fileciteturn20file0L38-L49 fileciteturn19file0L493-L498  
* якщо `tf=="1m"` і `closed_bars` не порожній — вони записуються в FileCache як `complete=True`, `source="stream_close"`, з деградацією на дублікати/помилки запису. fileciteturn19file0L498-L546

Сам `FileCache.append_complete_bars()` нормалізує вхідні бари, примусово встановлює `complete=True`, мержить по `open_time_ms` (“keep last”), тримає `UNIQUE(open_time_ms)` і атомарно пише CSV+meta. fileciteturn36file0L57-L88 fileciteturn37file0L103-L161

### Ключова невідповідність P10: “final 1m publish” у live зараз відсутній

P10 у `docs/Audit v7_1a.md` прямо вимагає: “Final: на закритті 1m — **запис у FileCache як SSOT final + публікація у {NS}:ohlcv**” та “market‑aware/gap policy/no silent repairs”. fileciteturn55file0L119-L137

Фактичний стан:  
* live шлях **не викликає** `publish_ohlcv_final_1m()`; він публікує лише preview (`publish_ohlcv_batch`, complete=false). fileciteturn19file0L479-L492 fileciteturn53file0L58-L85  
* `publish_ohlcv_final_1m()` має жорсткі інваріанти: final має `complete=true`, `synthetic=false`, `event_ts == close_time`, а `source` дозволений лише `{"history","history_agg"}`. fileciteturn53file0L86-L114 fileciteturn53file0L146-L166  
* “stream_close” як source **не пройде** `_validate_final_bars()` (бо source не в allowlist), а live “closed bars” навіть не містять `event_ts`. fileciteturn19file0L508-L531 fileciteturn53file0L146-L166

Тобто поточна реалізація робить “final‑подібний запис” у FileCache, але **не піднімає final‑wire протокол в Redis** для live (complete=true), і не оновлює `status.ohlcv_final_1m` як результат live‑finalization.

### Де final‑publish існує: лише для history‑tail, не для live stream_close

`app/composition.py::_publish_final_tail()` читає з FileCache (tf=1m) і публікує як final‑batch через `publish_ohlcv_final_1m()` з `source="history"` і `event_ts = close_time`. fileciteturn19file0L206-L253

Але цей callback використовується в warmup/backfill handlers, а не в live tick path. fileciteturn41file0L26-L59 fileciteturn41file0L61-L99

### Gap policy і “no silent repairs”: частково є (tail_guard/repair), але це не live‑finalization

Механізм gap policy фактично винесений у `tail_guard` + `repair`:

`runtime/tail_guard.py` для 1m:  
* бере “хвіст” з FileCache (`query(limit=window_hours*60)`),  
* знаходить розриви по `open_time_ms` і **враховує календар**: missing хвилини додаються лише якщо `calendar.is_open(t)` у конкретній хвилині; fileciteturn51file0L193-L233  
* може запускати repair, але лише (за замовчуванням) коли ринок закритий (`tail_guard_safe_repair_only_when_market_closed`). fileciteturn51file0L115-L135 fileciteturn67file0L104-L108

`runtime/repair.py` має budget rails: ліміти на span, missing bars, chunks; і робить fetch через history provider з `guard_history_ready()` перед ремонтом. fileciteturn52file0L40-L90 fileciteturn52file0L92-L135

Це відповідає “no silent repairs” **на рівні recovery/repair**, але P10 вимагав ще й **live‑finalization** + явну політику “що робимо з gap прямо у live” (поставити degraded, зупинити final, або ін.). Зараз live просто пише те, що вийшло зі стріму, а gap‑детекція відкладена на tail_guard.

## Консолідовані ризики та next steps, які логічно випливають з фактів

Нижче — не “патч‑план”, а технічні next steps у стилі “що перевірити/чим закрити прогалину”, щоб довести систему до критеріїв P8/P9/P10 з `docs/Audit v7_1a.md`. fileciteturn55file0L60-L143

### Ризики, які вже видно з коду

Проблема “tick stream stop semantics”: shared `_stop_event` в `FxcmForexConnectStream` створює класичний dataclass‑антипатерн “mutable default”, і в разі двох інстансів у процесі зупинка стане глобальною. Це ризик P8/P11 (restart‑safe lifecycle).
fileciteturn66file0L373-L396 fileciteturn55file0L148-L161

Проблема “market closed → next open”: `FxcmForexConnectStream` використовує `config.closed_intervals_utc` для next_open, але Calendar забороняє передавати `closed_intervals_utc` у рантайм‑Calendar напряму (SSOT — overrides.json).
Це означає, що “sleep до відкриття” фактично не має даних, і пауза зводиться до backoff‑циклу. fileciteturn66file0L459-L471 fileciteturn67file0L34-L38

Проблема “FXCM history 0 bars”: `_rows_to_bars()` не шукає `"Date"`, а в іншому репо тести показують, що dict‑history може мати саме `"Date"`. Це один з найвірогідніших кандидатів на причину “warmup/backfill порожні”
 прямо відповідає зафіксованому ризику audit v7 runtime/core. fileciteturn26file0L105-L114 fileciteturn58file0L30-L34 fileciteturn65file0L88-L92

Проблема “chunking semantics”: формула `chunk_end = t + chunk_ms - 1` + `t = chunk_end + 60_000` у `fetch_1m_final()` має неочевидну інтервальну семантику й може породжувати gap/drift на межах.
Без теста, що фіксує “coverage без пропусків”, P9 determinism юридично не закритий. fileciteturn26file0L160-L179 fileciteturn55file0L90-L109

Проблема “P10 live final invariants”: live шлях не має final‑publish (`complete=true`) і не може його мати в поточному контракті, бо final дозволяє лише `source=history|history_agg`, тоді як live використовує `source="stream_close"` і не формує `event_ts`.
fileciteturn19file0L508-L531 fileciteturn53file0L146-L166 fileciteturn55file0L119-L137

### Next steps у термінах “гейт/перевірка/фактичний доказ”, без виконання зараз

Щоб P8 відповідало власним acceptance criteria з audit‑доку, потрібен **інтеграційний лівнес‑доказ**, а не лише debounce‑юнит: поточний `gate_fxcm_tick_liveness` перевіряє тільки cooldown.
Мінімально — окремий gate (або розширення існуючого), який верифікує “ticks>0 за N секунд” і “tick_lag_ms sane” через status/метрики. fileciteturn25file0L10-L33 fileciteturn55file0L76-L84 fileciteturn21file0L522-L548

Щоб P9 було “deterministic” і не ламалося на форматі history, потрібні два короткі unit‑докази (саме як rails, а не e2e‑інтеграції):  
* тест/гейт на `_rows_to_bars()` з рядком dict, який має `"Date"` (і/або інші реально можливі ключі з SDK), щоб виключити “0 bars через key‑case”; fileciteturn26file0L105-L114 fileciteturn58file0L30-L34  
* тест “coverage без пропусків” для `fetch_1m_final()` (на сим‑провайдері або мок‑адаптері), щоб зафіксувати семантику `start_ms/end_ms` і правильність chunk‑кроку. fileciteturn26file0L160-L179 fileciteturn46file0L33-L62

Щоб P10 відповідало вимозі “finalization + publish complete=true”, потрібне явне рішення по контрактах: або  
* дозволяти “final source=stream_close” у final‑wire (і тоді додати `event_ts` у live finalization та узгодити NoMix‑політику при подальшому warmup/backfill), або  
* залишити final‑wire тільки як “history‑авторитет”, а live робити лише preview + запис у SSOT, але тоді в audit‑доку P10 треба змінювати acceptance (бо зараз він вимагає publish final у live).
Поточний `_validate_final_bars()` це рішення вже форсує (history/history_agg only). fileciteturn53file0L146-L166 fileciteturn55file0L119-L137 fileciteturn68file0L10-L50

Логічне “закриття прогалини” гейтами: `docs/Audit v7_1a.md` очікує `gate_fxcm_history_smoke.py` (P9) і `gate_live_final_invariants.py` (P10), але їх немає в `tools/exit_gates/manifest.json`.
Якщо audit‑док — SSOT roadmap, це треба або реалізувати, або синхронізувати документ із фактом (щоб не було “paper compliance”). fileciteturn55file0L90-L143 fileciteturn40file0L3-L35

Окремо по календарю (бо він впливає на P8/P10): Calendar вимагає SSOT‑дані в `config/calendar_overrides.json`, а runtime/core audit прямо зазначає ризик “calendar data gap”.
Без заповнених overrides ви або отримаєте неправильні open/close (що створює phantom gaps), або будете змушені тримати `closed_intervals_utc` порожнім і жити з “backoff‑петлею” замість точного next_open у paused_market_closed. fileciteturn67file0L23-L61 fileciteturn65file0L54-L93