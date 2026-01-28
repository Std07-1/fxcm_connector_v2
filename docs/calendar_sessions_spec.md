# Calendar Sessions Spec (SSOT, v1‑aligned)

## Основні правила
- Час — UTC epoch ms; recurrence-правила беруться з SSOT у config/calendar_overrides.json.
- Recurrence-правила задаються у локальному часі America/New_York (DST-aware):
  - Weekly open: неділя 17:00 NY.
  - Weekly close: пʼятниця 17:00 NY.
  - Daily break: 17:00–17:05 NY (пн‑чт).
- `closed_intervals_utc` — allowlist жорстких закриттів у форматі [start_ms, end_ms) (UTC), перекривають будь‑які сесії.
- TODO: додати святкові `closed_intervals_utc` для `fxcm_calendar_v1_utc_overrides` (SSOT дані).

## Інваріанти
- `is_trading_time(ts_ms)` → True лише якщо:
  - не у `closed_intervals_utc`,
  - не у weekend‑close,
  - не у daily break.
- `next_trading_open(ts_ms)` → наступний старт сесії (або кінець daily break).
- `next_trading_pause(ts_ms)` → найближча пауза (daily break або weekly close).

## Edge‑cases (мінімальний набір)
1) Остання 1m свічка перед daily break (зимовий час, EST):
   - 17:00 NY = 22:00 UTC, останній бар відкривається о 21:59 UTC.
2) Перша 1m свічка після daily break (EST):
   - перший бар відкривається о 22:05 UTC.
3) Weekend boundary (EST):
   - після Friday 17:00 NY (22:00 UTC) наступне відкриття лише Sunday 17:00 NY (22:00 UTC).
4) DST boundary:
   - Sunday 17:00 NY дає різний UTC: взимку 22:00 UTC, влітку 21:00 UTC.

## Режим деградації (degraded‑but‑loud)
- Якщо TZ не ініціалізовано або правила некоректні →
  - `calendar_error` у degraded,
  - запис у `errors[]` зі зрозумілим повідомленням,
  - без «тихого» fallback.
