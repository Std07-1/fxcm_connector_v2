# Audit v5 — Calendar / Sessions (as‑is)

Дата: 2026-01-22
Режим: read-only discovery

## Поточна логіка календаря

- Calendar — stub: `Calendar.is_open` базується лише на `closed_intervals_utc`. [core/time/calendar.py](core/time/calendar.py#L14-L22)
- `market_state` повертає `is_open`, `next_open_utc`, `next_pause_utc`, `calendar_tag`; next_* = `_utc_iso_now` (не розрахунок сесій). [core/time/calendar.py](core/time/calendar.py#L8-L27)
- `is_repair_window` забороняє repair під час market open (якщо `safe_only_when_market_closed=true`). [core/time/calendar.py](core/time/calendar.py#L31-L34), використання: [runtime/tail_guard.py](runtime/tail_guard.py#L109-L127)

## Поля статусу (market)

- status_v2.market: `is_open`, `next_open_utc`, `next_pause_utc`, `calendar_tag`. [core/contracts/public/status_v2.json](core/contracts/public/status_v2.json#L27-L41)
- Початковий snapshot містить `degraded: ["calendar_stub"]`. [runtime/status.py](runtime/status.py#L140)

## Сесії / паузи

- Розрахунок сесій відсутній (stub). Факт: `next_open_utc` = `next_pause_utc` = UTC now. [core/time/calendar.py](core/time/calendar.py#L8-L27)

## Edge cases (останній бар перед паузою / перший після)

- Явних правил у коді/контрактах не знайдено (немає прямого доказу у source). Поведінка залежить від Calendar.is_open та факту надходження history/ticks. [core/time/calendar.py](core/time/calendar.py#L14-L22)
