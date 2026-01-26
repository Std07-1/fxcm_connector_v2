# V2 Public Surface (as-is)

Дата: 2026-01-22
Режим: read-only discovery

## Redis keys/channels

| Surface | Schema | Writer (де пише) | Reader (де читає) |
|---|---|---|---|
| `{NS}:status:snapshot` | status_v2 | StatusManager.publish_snapshot: [runtime/status.py](runtime/status.py#L931-L948) | HTTP /api/status: [runtime/http_server.py](runtime/http_server.py#L68-L79) |
| `{NS}:commands` | commands_v1 | client→Redis (external) | CommandBus: [runtime/command_bus.py](runtime/command_bus.py#L1-L114) |
| `{NS}:ohlcv` | ohlcv_v1 | Preview publish: [app/composition.py](app/composition.py#L375-L415); Republish: [runtime/republish.py](runtime/republish.py#L15-L77); Rebuild HTF publish: [runtime/rebuild_derived.py](runtime/rebuild_derived.py#L304-L307) | UI Lite WS: [ui_lite/server.py](ui_lite/server.py#L300-L470) |
| `{NS}:price_tik` | tick_v1 | TickPublisher: [runtime/tick_feed.py](runtime/tick_feed.py#L15-L52) | tools/record_ticks.py: [tools/record_ticks.py](tools/record_ticks.py#L64-L123) |

Де визначено namespace/канали:
- [config/config.py](config/config.py#L110-L130)

## HTTP

- `/api/status` → Redis key `{NS}:status:snapshot`: [runtime/http_server.py](runtime/http_server.py#L68-L79)
- `/api/ohlcv` → final (SQLite) або preview (in‑memory cache): [runtime/http_server.py](runtime/http_server.py#L81-L125)
- `/metrics` → Prometheus server: [observability/metrics.py](observability/metrics.py#L290-L292)
- `/chart` → static HTML: [runtime/http_server.py](runtime/http_server.py#L128-L136)

## JSON schemas

- status_v2: [core/contracts/public/status_v2.json](core/contracts/public/status_v2.json#L1)
- commands_v1: [core/contracts/public/commands_v1.json](core/contracts/public/commands_v1.json#L1)
- ohlcv_v1: [core/contracts/public/ohlcv_v1.json](core/contracts/public/ohlcv_v1.json#L1)
- tick_v1: [core/contracts/public/tick_v1.json](core/contracts/public/tick_v1.json#L1)

## Payload інваріанти (as-is)

- tick_ts/snap_ts у ms: [core/validation/validator.py](core/validation/validator.py#L28-L33), [tools/exit_gates/gates/gate_tick_units.py](tools/exit_gates/gates/gate_tick_units.py#L1-L31)
- OHLCV boundary + close_time inclusive: [core/validation/validator.py](core/validation/validator.py#L81-L92), [store/schema.sql](store/schema.sql#L19-L22)
- final 1m: source=history, event_ts==close_time: [store/schema.sql](store/schema.sql#L19-L23)
- final HTF: source=history_agg, event_ts==close_time: [store/schema.sql](store/schema.sql#L56-L75)
