# Audit v5 — Public Surface (as‑is)

Дата: 2026-01-22
Режим: read-only discovery

## Redis keys/channels

| Surface | Schema | Writer | Reader |
|---|---|---|---|
| `{NS}:status:snapshot` | [core/contracts/public/status_v2.json](core/contracts/public/status_v2.json#L1) | StatusManager.publish_snapshot: [runtime/status.py](runtime/status.py#L931-L948) | HTTP /api/status: [runtime/http_server.py](runtime/http_server.py#L68-L79) |
| `{NS}:commands` | [core/contracts/public/commands_v1.json](core/contracts/public/commands_v1.json#L1) | external clients | CommandBus: [runtime/command_bus.py](runtime/command_bus.py#L1-L114) |
| `{NS}:ohlcv` | [core/contracts/public/ohlcv_v1.json](core/contracts/public/ohlcv_v1.json#L1) | Preview publish: [app/composition.py](app/composition.py#L375-L415); Republish: [runtime/republish.py](runtime/republish.py#L15-L77); HTF publish: [runtime/rebuild_derived.py](runtime/rebuild_derived.py#L304-L307) | UI Lite WS: [ui_lite/server.py](ui_lite/server.py#L380-L470) |
| `{NS}:price_tik` | [core/contracts/public/tick_v1.json](core/contracts/public/tick_v1.json#L1) | TickPublisher: [runtime/tick_feed.py](runtime/tick_feed.py#L15-L52) | tools/record_ticks.py: [tools/record_ticks.py](tools/record_ticks.py#L64-L123) |

Канали/keys задаються в конфігу:
- [config/config.py](config/config.py#L110-L130)

## HTTP endpoints

- `/api/status` → Redis `{NS}:status:snapshot`: [runtime/http_server.py](runtime/http_server.py#L68-L79)
- `/api/ohlcv` → final (SQLite) або preview (cache): [runtime/http_server.py](runtime/http_server.py#L81-L125)
- `/metrics` → Prometheus server: [observability/metrics.py](observability/metrics.py#L290-L292)
- `/chart` → static HTML: [runtime/http_server.py](runtime/http_server.py#L128-L136)

## Payload інваріанти (as‑is)

- tick_ts/snap_ts у ms: [core/validation/validator.py](core/validation/validator.py#L28-L33)
- open_time/close_time ms: [core/validation/validator.py](core/validation/validator.py#L153-L160)
- close_time inclusive: [core/time/buckets.py](core/time/buckets.py#L52-L69)
- final 1m source/history + event_ts==close_time: [store/schema.sql](store/schema.sql#L19-L23)
- final HTF source/history_agg + event_ts==close_time: [store/schema.sql](store/schema.sql#L56-L75)
