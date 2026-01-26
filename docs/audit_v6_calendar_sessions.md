# Audit v6 — Calendar sessions (read-only)

## Поточна модель (stub)
- Календар реалізовано як мінімальний stub `Calendar`, що використовує список закритих інтервалів `closed_intervals_utc` — [core/time/calendar.py](core/time/calendar.py#L11-L22).
- `is_open()` повертає `False`, якщо ts потрапляє у закритий інтервал, інакше `True` — [core/time/calendar.py](core/time/calendar.py#L20-L24).
- `market_state()` повертає `is_open`, `next_open_utc`, `next_pause_utc` та `calendar_tag` (для stub — поточний UTC час) — [core/time/calendar.py](core/time/calendar.py#L26-L35).

## Джерела параметрів
- `calendar_tag`, `trading_day_boundary_utc`, `closed_intervals_utc` задаються у конфігу — [config/config.py](config/config.py#L42-L44).

## Repair window
- `is_repair_window()` дозволяє repair лише коли ринок закритий, якщо `safe_only_when_market_closed=True` — [core/time/calendar.py](core/time/calendar.py#L37-L40).
- Значення `tail_guard_safe_repair_only_when_market_closed` за замовчуванням `True` — [config/config.py](config/config.py#L63-L63).

## Висновок
- Явної таблиці сесій у коді немає; модель базується на closed-інтервалах та stub-стані ринку — [core/time/calendar.py](core/time/calendar.py#L11-L35).
