# V2 Time & Calendar Semantics (as-is)

Дата: 2026-01-22
Режим: read-only discovery

## Канонічні правила часу

- Час у системі — UTC epoch ms (tick_ts/snap_ts/open_time/close_time). Enforced: [core/validation/validator.py](core/validation/validator.py#L28-L33), [core/contracts/public/tick_v1.json](core/contracts/public/tick_v1.json#L1-L11).
- close_time inclusive: `close_time = open_time + TF - 1`. Enforced: [core/time/buckets.py](core/time/buckets.py#L52-L69), [core/validation/validator.py](core/validation/validator.py#L81-L92), [store/schema.sql](store/schema.sql#L19-L22).
- Для 1m: open_time має бути кратний 60_000. Enforced: [core/validation/validator.py](core/validation/validator.py#L81-L92).
- Для 1d: boundary враховує trading_day_boundary_utc. Enforced: [core/time/buckets.py](core/time/buckets.py#L33-L61) + validator: [core/validation/validator.py](core/validation/validator.py#L81-L88).

## Trading time / calendar

- Calendar — stub (мінімальна логіка) і позначається degraded. [core/time/calendar.py](core/time/calendar.py#L14-L27), [runtime/status.py](runtime/status.py#L140).
- repair_window: `Calendar.is_repair_window` блокує repair коли market open. [core/time/calendar.py](core/time/calendar.py#L31-L34) + використання: [runtime/tail_guard.py](runtime/tail_guard.py#L109-L127).

## Boundary для 1d

- `trading_day_boundary_utc` заданий у конфігу (HH:MM) і використовується для 1d. [config/config.py](config/config.py#L44-L48), [core/time/buckets.py](core/time/buckets.py#L33-L61).

## Edge cases (якщо є доказ)

- Last bar before break/weekend: явних правил у коді не знайдено (немає прямого доказу у source). Поведінка залежить від Calendar.is_open та store tail. [core/time/calendar.py](core/time/calendar.py#L14-L27), [runtime/tail_guard.py](runtime/tail_guard.py#L211-L239).
- First bar after break/weekend: явних правил у коді не знайдено (немає прямого доказу у source). Потік визначається входом history/ticks.
