# MVP parity план: warmup/backfill/republish_tail/tail_guard

## Мета
Забезпечити робочий і відтворюваний ланцюжок прогріву SSOT (warmup), цільового поповнення історії (backfill), репаблішу фінальних барів (republish_tail) та аудиту/ремонту хвоста (tail_guard) з явними критеріями перевірки.

## Джерела правди (SSOT)
- Командні хендлери: [app/composition.py](../../app/composition.py#L330-L640)
- Парсинг warmup/backfill аргументів: [runtime/handlers_p3.py](../../runtime/handlers_p3.py#L24-L100)
- Warmup реалізація: [runtime/warmup.py](../../runtime/warmup.py#L15)
- Backfill реалізація: [runtime/backfill.py](../../runtime/backfill.py#L15)
- Republish tail реалізація: [runtime/republish.py](../../runtime/republish.py#L15)
- Tail guard реалізація: [runtime/tail_guard.py](../../runtime/tail_guard.py#L45)
- Статусні записи (final/republish/tail_guard): [runtime/status.py](../../runtime/status.py#L1033-L1278)
- Ключові конфіги: [config/config.py](../../config/config.py#L50-L91)
- Контракт команд: [core/contracts/public/commands_v1.json](../../core/contracts/public/commands_v1.json)

## Команди та аргументи
### Загальний контракт
Будь-яка команда має відповідати schema commands_v1 (обов’язково `cmd`, `req_id`, `ts`, `args`; опційно `auth`).

### Warmup (`fxcm_warmup`)
- Хендлер: `handle_warmup_command` → `run_warmup`.
- Аргументи:
  - `symbols`: list[str] або str (обов’язково непорожній список).
  - `lookback_days` або `lookback_hours` (якщо hours → округлення до днів).
  - `publish`: bool (за замовчуванням true).
  - `window_hours`: int (для republish tail після warmup, дефолт 24).
  - `provider`: ім’я провайдера історії.

### Backfill (`fxcm_backfill`)
- Хендлер: `handle_backfill_command` → `run_backfill`.
- Аргументи:
  - `symbol`: str (обов’язковий).
  - `start_ms`/`end_ms` або `start_utc`/`end_utc`.
  - `publish`: bool (за замовчуванням true).
  - `window_hours`: int (для republish tail після backfill, дефолт 24).
  - `provider`: ім’я провайдера історії.

### Republish tail (`fxcm_republish_tail`)
- Хендлер: `_handle_republish_tail` → `republish_tail`.
- Аргументи:
  - `symbol`: str (обов’язковий).
  - `timeframes`: list[str] (обов’язковий; для 1m або HTF).
  - `window_hours`: int (дефолт `republish_tail_window_hours_default`).
  - `force`: bool (ігнорує watermark).

### Tail guard (`fxcm_tail_guard`)
- Хендлер: `_handle_tail_guard` → `run_tail_guard`.
- Аргументи:
  - `symbols`: list[str] або str (обов’язково непорожній список).
  - `window_hours`: int (дефолт `tail_guard_default_window_hours`).
  - `repair`: bool (вмикає repair, за замовчуванням false).
  - `republish_after_repair`: bool (за замовчуванням true).
  - `republish_force`: bool (за замовчуванням false).
  - `tfs`: list[str] або str (дефолт `tail_guard_allow_tfs`).
  - `provider`: ім’я провайдера історії (для repair).

### Bootstrap (`fxcm_bootstrap`)
- Хендлер: `_handle_bootstrap`.
- Увімкнення: `bootstrap_enable=true`.
- Ланцюжок: warmup → backfill → republish_tail (якщо `bootstrap_republish_after_backfill`) → tail_guard (якщо `bootstrap_tail_guard_after`).

## Потоки та ключова логіка
### Warmup
- `run_warmup` робить historical fetch 1m з чанками (`history_chunk_minutes`, `history_chunk_limit`), маркує `complete=True`, записує у FileCache, оновлює:
  - coverage (`record_final_1m_coverage`),
  - final publish (`record_final_publish`).
- За `publish=true` тригериться republish tail через callback.

### Backfill
- `run_backfill` виконує fetch у діапазоні `[start_ms, end_ms]` з тими ж чанками, оновлює coverage + final publish.
- Якщо переданий callback — після кожного чанку публікує tail.

### Republish tail
- `republish_tail` публікує фінальні бари з FileCache, розбиває на батчі (`max_bars_per_message`).
- Використовує watermark у Redis (`republish_watermark_ttl_s`).
- Рейка безпеки: дозволені лише final-джерела `history`/`history_agg` (для 1m → тільки `history`).

### Tail guard
- `run_tail_guard` аудує тільки `1m` (інші TF помічені як `unsupported`).
- Пошук missing ranges базується на календарі і gap-ах у 1m.
- `repair=true` дозволений лише коли `tail_guard_safe_repair_only_when_market_closed=true` і ринок закритий.
- За `republish_after_repair=true` після repair робиться `republish_tail` для `1m`.
- Пише `tail_guard` статус у двох тирах: `near` (коротке вікно) і `far` (основне вікно).

## План досягнення MVP parity
1) **Пре-чек середовища**
   - `cache_enabled=true` (інакше warmup/backfill/republish/tail_guard заборонені).
   - Наявний history provider (`history_provider_kind != none`).
   - Redis доступний (watermark для republish + command bus).

2) **Warmup (створення базового SSOT)**
   - Запустити `fxcm_warmup` для `fxcm_symbols` з `lookback_days` = `warmup_lookback_days`.
   - Очікування: `ohlcv.final_1m.coverage_ok=true` та оновлений `ohlcv_final_1m`.

3) **Backfill (закриття явних провалів)**
   - Визначити діапазони для backfill (наприклад, через tail_guard audit або зовнішню верифікацію).
   - Запустити `fxcm_backfill` для кожного символу та діапазону.

4) **Republish tail (публікація фіналу)**
   - Запустити `fxcm_republish_tail` для `1m` (window_hours = `republish_tail_window_hours_default`).
   - Для HTF — лише після того, як downstream гарантує `last_write_source=history_agg`.

5) **Tail guard (аудит + repair)**
   - Запустити `fxcm_tail_guard` з `repair=false` для аудиту.
   - Якщо виявлено missing ranges і ринок закритий — повторити з `repair=true`.
   - За потреби увімкнути `republish_after_repair=true`.

6) **Верифікація parity**
   - Статус: `ohlcv.final_1m.coverage_ok=true`, `republish.state=ok|skipped`, `tail_guard.*.tf_states["1m"].state=ok`.
   - Метрики: зростають `connector_warmup_requests_total`, `connector_backfill_requests_total`, `connector_republish_runs_total`, `connector_tail_guard_runs_total`.

## Критерії готовності (DoD)
- Warmup і backfill оновили `ohlcv.final_1m` та `ohlcv_final` без помилок контракту.
- Republish tail не падає на `republish_source_invalid`.
- Tail guard для `1m` повертає `missing_bars=0` у `far` tier.
- У status немає нових критичних `errors[]` для цих потоків.

## Ризики та обмеження
- Tail guard наразі аудує лише `1m` (інші TF не перевіряються).
- Republish tail заборонено, якщо `last_write_source` не у final-джерелах.
- Repair можливий лише при закритому ринку (за замовчуванням).
- Командний payload і auth мають відповідати rails command bus.

## Примітки
- Якщо використовується `fxcm_bootstrap`, переконатись що `bootstrap_enable=true` та задані аргументи для всіх потрібних кроків.
- Для великих діапазонів backfill враховувати ліміти `history_chunk_*` та history budget.
