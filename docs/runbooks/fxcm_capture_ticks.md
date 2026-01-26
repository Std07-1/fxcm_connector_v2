# Runbook: FXCM capture ticks → JSONL fixtures

## Мета
- Зняти коротку вибірку ticks з ForexConnect OFFERS та зберегти у JSONL для детермінованих тестів.

## Принципи
- Короткі сесії (30–60 с), 1–2 символи.
- Не логувати секрети.
- tick_ts_ms та snap_ts_ms строго epoch ms (int).
- Якщо FXCM SDK/creds недоступні — hard fail.

## Кроки (manual smoke)
1) Активувати venv:
   - .\.venv\Scripts\Activate.ps1
2) Переконатися, що .env.local/.env.prod містить FXCM креденшали.
3) Запустити capture:
   - python tools/capture_fxcm_ticks.py --symbols XAUUSD --duration_s 30 --out_dir recordings/fxcm_ticks --tag smoke
4) Валідація fixtures:
   - python tools/validate_tick_fixtures.py --in recordings/fxcm_ticks/<file>.jsonl --max_lines 50

## Очікуваний формат JSONL
Кожен рядок:

```
{"symbol":"XAUUSD","bid":...,"ask":...,"mid":...,"tick_ts_ms":1700000000000,"snap_ts_ms":1700000000001}
```

## Обмеження
- Не запускати довгі capture-сесії під час live-сесій.
- Якщо FXCM не відповідає — зачекати і повторити (backoff).
