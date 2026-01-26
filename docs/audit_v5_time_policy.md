# Audit v5 — Time Policy (as‑is)

Дата: 2026-01-22
Режим: read-only discovery

## Units (ms/sec/us)

- Канонічно очікується UTC epoch **ms int** (мінімум 1e12). [core/validation/validator.py](core/validation/validator.py#L28-L33)
- Upper bound проти μs **не визначено** (у `_require_ms_int` лише нижня межа). [core/validation/validator.py](core/validation/validator.py#L28-L33)

## Нормалізації/конверсії

- `open_time_ms / 1000 → time_s` у UI Lite server. [ui_lite/server.py](ui_lite/server.py#L198-L206)
- `open_time / 1000 → time` у UI adapter, якщо немає `bar.time`. [ui_lite/static/chart_adapter.js](ui_lite/static/chart_adapter.js#L15-L20)
- `datetime → epoch ms` у `to_epoch_ms_utc`. [core/time/timestamps.py](core/time/timestamps.py#L8-L25)

## Формування tick_ts_ms/snap_ts_ms

- FXCM offers використовує wall‑clock `now_ms` як tick_ts_ms/snap_ts_ms. [runtime/fxcm_forexconnect.py](runtime/fxcm_forexconnect.py#L186-L202)
- TickPublisher публікує `tick_ts`/`snap_ts` як отримані значення (без нормалізації). [runtime/tick_feed.py](runtime/tick_feed.py#L28-L52)

## Boundary rules

- close_time inclusive: `open_time + TF − 1`. [core/time/buckets.py](core/time/buckets.py#L52-L69)
- Bucket open для 1d з `trading_day_boundary_utc`. [core/time/buckets.py](core/time/buckets.py#L33-L61), config: [config/config.py](config/config.py#L44-L48)

## Wall‑clock ризик

- Wall‑clock ticks під час market=CLOSED можливі через FXCM offers (немає зовнішнього timestamp). [runtime/fxcm_forexconnect.py](runtime/fxcm_forexconnect.py#L186-L202)
- UI може інтерпретувати ms/us як seconds, якщо `bar.time` приходить без нормалізації. [ui_lite/static/chart_adapter.js](ui_lite/static/chart_adapter.js#L15-L20)
