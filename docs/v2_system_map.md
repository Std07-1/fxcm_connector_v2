# V2 System Map (as-is)

Дата: 2026-01-22
Режим: read-only discovery

## Архітектурна схема (ASCII)

```
app/main.py
  → command_bus
  → handlers
  → store/sqlite
  → derived_builder
  → publisher
  → Redis
```

Докази основних вузлів:
- app/main → build_runtime/loop: [app/main.py](app/main.py#L1-L59)
- command_bus: [runtime/command_bus.py](runtime/command_bus.py#L1-L114)
- handlers (warmup/backfill/republish/tail_guard) wiring: [app/composition.py](app/composition.py#L140-L308)
- store/sqlite: [store/sqlite_store.py](store/sqlite_store.py#L1-L120)
- derived_builder: [store/derived_builder.py](store/derived_builder.py#L31-L123)
- publisher: [runtime/publisher.py](runtime/publisher.py#L1-L70)
- Redis channels: [config/config.py](config/config.py#L110-L130)

## Відповідальності модулів (as-is)

- app/main.py — entrypoint: читає env/config, запускає runtime і loop publish_snapshot. [app/main.py](app/main.py#L1-L59)
- app/composition.py — композиція залежностей (Redis/SQLite/HTTP/Preview/FXCM) + handlers. [app/composition.py](app/composition.py#L1-L140)
- runtime/command_bus.py — валідована обробка команд з Redis, no silent fallback. [runtime/command_bus.py](runtime/command_bus.py#L1-L215)
- runtime/status.py — SSOT статусу, build/publish snapshot, rails (payload size, NoMix mirror). [runtime/status.py](runtime/status.py#L16-L948)
- runtime/http_server.py — HTTP /api/status, /api/ohlcv, /chart. [runtime/http_server.py](runtime/http_server.py#L63-L136)
- runtime/preview_builder.py — preview OHLCV з ticks, late‑tick rail. [runtime/preview_builder.py](runtime/preview_builder.py#L87-L173)
- runtime/ohlcv_preview.py — обгортка PreviewBuilder. [runtime/ohlcv_preview.py](runtime/ohlcv_preview.py#L1-L34)
- runtime/warmup.py — warmup history → SQLite + status. [runtime/warmup.py](runtime/warmup.py#L44-L92)
- runtime/backfill.py — backfill history → SQLite + status. [runtime/backfill.py](runtime/backfill.py#L49-L92)
- runtime/rebuild_derived.py — rebuild HTF final з 1m SSOT + publish. [runtime/rebuild_derived.py](runtime/rebuild_derived.py#L87-L207)
- runtime/tail_guard.py — audit/repair tail, marks/TTL + optional republish. [runtime/tail_guard.py](runtime/tail_guard.py#L43-L190)
- runtime/republish.py — republish tail з watermark TTL. [runtime/republish.py](runtime/republish.py#L15-L77)
- store/sqlite_store.py — SSOT 1m final + HTF final таблиці/інваріанти. [store/sqlite_store.py](store/sqlite_store.py#L1-L120)
- store/derived_builder.py — агрегація 1m → HTF final. [store/derived_builder.py](store/derived_builder.py#L31-L123)
- core/validation/validator.py — контракти + інваріанти часу/границь/ключів. [core/validation/validator.py](core/validation/validator.py#L28-L225)
- core/time/buckets.py — bucket boundary + close_time semantics. [core/time/buckets.py](core/time/buckets.py#L3-L69)
- core/time/calendar.py — stub calendar + repair window. [core/time/calendar.py](core/time/calendar.py#L14-L34)
- observability/metrics.py — /metrics server + counters. [observability/metrics.py](observability/metrics.py#L1-L292)
- tools/exit_gates/* — перелік gate-скриптів (manifest). [tools/exit_gates/manifest.json](tools/exit_gates/manifest.json#L1-L20)

## DRIFT/RISKS (as-is)

- SSOT може бути порожнім (ssot_empty) і це не завжди блокує інші потоки. Факти: [runtime/tail_guard.py](runtime/tail_guard.py#L63-L83), [runtime/status.py](runtime/status.py#L690-L707).
- Дублікат полів у статусі: `ohlcv_final_1m` і `ohlcv_final["1m"]` з дзеркалюванням. Факти: [runtime/status.py](runtime/status.py#L629-L710).
- Boundary/trading_time визначаються у core/time/buckets.py + validator + store CHECK (ризик дрейфу). Факти: [core/time/buckets.py](core/time/buckets.py#L3-L69), [core/validation/validator.py](core/validation/validator.py#L81-L92), [store/schema.sql](store/schema.sql#L19-L75).
