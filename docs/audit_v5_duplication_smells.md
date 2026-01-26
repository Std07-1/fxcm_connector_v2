# Audit v5 — Duplication / Smells (as‑is)

Дата: 2026-01-22
Режим: read-only discovery

## Повторні time‑utils (wall‑clock)

- _now_ms у status: [runtime/status.py](runtime/status.py#L39-L40)
- warmup: [runtime/warmup.py](runtime/warmup.py#L47-L82)
- backfill: [runtime/backfill.py](runtime/backfill.py#L65-L84)
- tail_guard: [runtime/tail_guard.py](runtime/tail_guard.py#L66-L211)
- republish: [runtime/republish.py](runtime/republish.py#L29)
- rebuild_derived: [runtime/rebuild_derived.py](runtime/rebuild_derived.py#L202-L264)

Ризик: “utils hell” + різні правила wall‑clock (market closed/open). SSOT кандидати: core/time/timestamps.py.

## Повторні boundary правила

- Buckets: [core/time/buckets.py](core/time/buckets.py#L3-L69)
- Validator boundary: [core/validation/validator.py](core/validation/validator.py#L81-L92)
- SQLite CHECK: [store/schema.sql](store/schema.sql#L19-L75)
- Gates: [tools/exit_gates/gates/gate_final_wire.py](tools/exit_gates/gates/gate_final_wire.py#L1-L56)

Ризик: дрейф визначень boundary між шарами.

## Повторні OHLCV мапінги (final)

- HTTP final mapping: [runtime/http_server.py](runtime/http_server.py#L96-L117)
- Republish tail mapping: [runtime/republish.py](runtime/republish.py#L48-L71)
- HTF publish mapping: [runtime/rebuild_derived.py](runtime/rebuild_derived.py#L278-L307)

Ризик: різні поля/імена в різних потоках.

## Повторні нормалізації часу у UI

- UI Lite server `/1000`: [ui_lite/server.py](ui_lite/server.py#L198-L206)
- UI adapter `/1000`: [ui_lite/static/chart_adapter.js](ui_lite/static/chart_adapter.js#L15-L20)

Ризик: різні unit‑assumptions у UI шарах.
