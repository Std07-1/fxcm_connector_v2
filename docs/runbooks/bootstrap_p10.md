# Runbook: P10 bootstrap (warmup → backfill → republish_tail)

## Мета
Забезпечити, що після рестарту UI має final‑дані в Redis без змішування джерел. Final‑wire (complete=true) **лише** history/history_agg.

## Умови
- `bootstrap_enable=true` у Config.
- `cache_enabled=true` (FileCache обов’язковий).
- Tail‑guard запускається лише якщо `bootstrap_tail_guard_after=true` і задані args.

## Команда (Redis {NS}:commands)
Приклад payload для `fxcm_bootstrap`:

```json
{
  "cmd": "fxcm_bootstrap",
  "req_id": "boot-001",
  "ts": 1700000000000,
  "args": {
    "warmup": {
      "symbols": ["XAUUSD"],
      "lookback_days": 7,
      "publish": true,
      "window_hours": 24
    },
    "backfill": {
      "symbol": "XAUUSD",
      "start_utc": "2026-01-25T00:00:00Z",
      "end_utc": "2026-01-31T23:59:59Z",
      "publish": true,
      "window_hours": 24
    },
    "republish_tail": {
      "symbol": "XAUUSD",
      "timeframes": ["1m"],
      "window_hours": 24,
      "force": true
    },
    "tail_guard": {
      "symbols": ["XAUUSD"],
      "timeframes": ["1m"],
      "window_hours": 24,
      "repair": false,
      "republish_after_repair": false,
      "republish_force": false
    }
  }
}
```

## Перевірки
1) Redis:
- `{NS}:ohlcv` містить final‑payloads (complete=true, source=history/history_agg).
2) HTTP:
- `/api/ohlcv?mode=final&symbol=XAUUSD&tf=1m` повертає бари з FileCache.
- `/api/status` показує `bootstrap.state/step`.

## Нотатки
- Якщо FileCache останнього запису має `last_write_source=stream/stream_close`, `republish_tail` **hard-fail**.
- Для live‑finalization потрібен наступний slice P10.B (reconcile‑фіналізація).