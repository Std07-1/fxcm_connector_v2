# Audit v6 — Public surface (read-only)

## HTTP API (read-only chart)
- Порт HTTP зафіксований у run-only snapshot — [data/audit_v6/env_snapshot.txt](data/audit_v6/env_snapshot.txt#L2-L9) і задається конфігом — [config/config.py](config/config.py#L101-L101).
- `/api/status` → JSON зі status:snapshot — [runtime/http_server.py](runtime/http_server.py#L66-L98).
- `/api/ohlcv?symbol=&tf=&mode=&limit=` → preview/final бари — [runtime/http_server.py](runtime/http_server.py#L81-L127).
- `/chart` → compatibility stub: redirect на UI Lite (без runtime/static) — [runtime/http_server.py](runtime/http_server.py#L128-L149).

## UI Lite (HTTP + WS)
- Увімкнення і порт UI Lite — [config/config.py](config/config.py#L81-L83).
- `/debug` → JSON зі станом UI Lite — [ui_lite/server.py](ui_lite/server.py#L133-L146).
- `/`, `/index.html`, `/app.js`, `/styles.css`, `/chart_adapter.js` → статичні ресурси UI — [ui_lite/server.py](ui_lite/server.py#L146-L178).

## Metrics
- `/metrics` сервер стартує через `start_metrics_server()` — [observability/metrics.py](observability/metrics.py#L287-L293).
- Порт метрик задається конфігом — [config/config.py](config/config.py#L28-L29).

## Redis Pub/Sub + ключі
- Канали: `ch_status()`, `ch_commands()`, `ch_price_tik()`, `ch_ohlcv()` — [config/config.py](config/config.py#L110-L127).
- Ключ snapshot: `key_status_snapshot()` — [config/config.py](config/config.py#L130-L131).
