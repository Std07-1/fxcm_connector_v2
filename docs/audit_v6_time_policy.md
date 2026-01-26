# Audit v6 — Time policy (read-only)

## Bucket policy (ms)
- Карта TF→ms: 1m/5m/15m/1h/4h/1d — [core/time/buckets.py](core/time/buckets.py#L5-L12).
- `floor_to_bucket_ms()` вирівнює ts у ms до початку bucket (mod size) і відхиляє невідомі TF — [core/time/buckets.py](core/time/buckets.py#L15-L21).
- `bucket_end_ms()` та `bucket_close_ms()` визначають верхню межу та inclusive close (`end-1`) — [core/time/buckets.py](core/time/buckets.py#L47-L55).

## Trading day boundary (UTC)
- `trading_day_boundary_utc` конфіг (HH:MM) — [config/config.py](config/config.py#L42-L44).
- `_parse_boundary_utc()` і `trading_day_boundary_offset_ms()` валідуюють формат і рахують зсув — [core/time/buckets.py](core/time/buckets.py#L22-L40).
- `get_bucket_open_ms()` застосовує boundary лише для TF `1d`, інші TF — через `floor_to_bucket_ms()` — [core/time/buckets.py](core/time/buckets.py#L58-L63).
- `get_bucket_close_ms()` повертає inclusive close з урахуванням TF — [core/time/buckets.py](core/time/buckets.py#L65-L68).

## Calendar tag
- Тег календаря визначається в конфігу — [config/config.py](config/config.py#L42-L42).
