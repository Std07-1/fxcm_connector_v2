# Audit v6 — System map (read-only)

## Контекст середовища (run-only)
- Параметри середовища і локальні значення NS/портів/шляху сховища зафіксовані у [data/audit_v6/env_snapshot.txt](data/audit_v6/env_snapshot.txt#L2-L9).
- Status snapshot зчитано через redis-cli — [data/audit_v6/status_snapshot.json](data/audit_v6/status_snapshot.json#L1).

## Основні компоненти і ролі
1) SSOT конфіг (джерело параметрів)
- NS/канали/ключі, порти та календарні налаштування визначені у конфігу — [config/config.py](config/config.py#L12-L131).

2) Redis статус/канали
- Канали `ch_status()`, `ch_commands()`, `ch_price_tik()`, `ch_ohlcv()` та ключ `key_status_snapshot()` формуються в конфігу — [config/config.py](config/config.py#L110-L131).
- Публікація status:snapshot та pub/sub status відбуваються у `publish_snapshot()` — [runtime/status.py](runtime/status.py#L936-L956).

3) HTTP read-only API (chart)
- `/api/status` читає snapshot ключ і повертає JSON — [runtime/http_server.py](runtime/http_server.py#L66-L98).
- `/api/ohlcv` повертає preview або final з SQLite — [runtime/http_server.py](runtime/http_server.py#L81-L127).
- `/chart` віддає статичний HTML — [runtime/http_server.py](runtime/http_server.py#L128-L136).

4) UI Lite (web UI + debug)
- `/debug` повертає runtime snapshot стану UI Lite — [ui_lite/server.py](ui_lite/server.py#L133-L146).
- Статичні ресурси UI Lite (`/`, `/index.html`, `/app.js`, `/styles.css`, `/chart_adapter.js`) — [ui_lite/server.py](ui_lite/server.py#L146-L178).

5) Metrics
- `/metrics` сервер стартує через `start_metrics_server()` — [observability/metrics.py](observability/metrics.py#L287-L293).
- Порт метрик задається конфігом — [config/config.py](config/config.py#L28-L29).

6) Store (SQLite)
- Шлях до локального SQLite сховища визначений у конфігу — [config/config.py](config/config.py#L48-L49).
- Фактичне значення у середовищі зафіксовано — [data/audit_v6/env_snapshot.txt](data/audit_v6/env_snapshot.txt#L8-L9).

## Потоки даних (узагальнено)
- Команди і статус через Redis Pub/Sub + snapshot key — [config/config.py](config/config.py#L110-L131), [runtime/status.py](runtime/status.py#L936-L956).
- HTTP API читає status snapshot через Redis — [runtime/http_server.py](runtime/http_server.py#L66-L98).
- UI Lite читає дані через Redis і віддає web UI + `/debug` — [ui_lite/server.py](ui_lite/server.py#L133-L178).

## Обмеження/стан v6
- У snapshot присутні `errors[]` і `degraded[]` (зокрема `tick_contract_reject`, `calendar_stub`) — [data/audit_v6/status_snapshot.json](data/audit_v6/status_snapshot.json#L1).
