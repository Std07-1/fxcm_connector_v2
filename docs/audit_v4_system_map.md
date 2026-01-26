# E2E System Map v2

Дата: 2026-01-22
Режим: read-only discovery (код не змінювався)

## Public surface (Redis + HTTP)

| Поверхня | Призначення | Контракт/схема | Де визначено |
|---|---|---|---|
| `{NS}:status:snapshot` | Redis key зі snapshot статусу | [core/contracts/public/status_v2.json](core/contracts/public/status_v2.json#L1) | [config/config.py](config/config.py#L130) |
| `{NS}:commands` | Команди (Pub/Sub) | [core/contracts/public/commands_v1.json](core/contracts/public/commands_v1.json#L1) | [config/config.py](config/config.py#L115) |
| `{NS}:ohlcv` | OHLCV wire (preview/final) | [core/contracts/public/ohlcv_v1.json](core/contracts/public/ohlcv_v1.json#L1) | [config/config.py](config/config.py#L125) |
| `{NS}:price_tik` | Tick стрім | [core/contracts/public/tick_v1.json](core/contracts/public/tick_v1.json#L1) | [config/config.py](config/config.py#L120) |
| `/api/status` | HTTP status snapshot | [core/contracts/public/status_v2.json](core/contracts/public/status_v2.json#L1) | [runtime/http_server.py](runtime/http_server.py#L68-L79) |
| `/api/ohlcv` | HTTP OHLCV (final/preview) | [core/contracts/public/ohlcv_v1.json](core/contracts/public/ohlcv_v1.json#L1) | [runtime/http_server.py](runtime/http_server.py#L81-L125) |
| `/metrics` | Prometheus метрики | (Prometheus) | [observability/metrics.py](observability/metrics.py#L290-L292), порт: [config/config.py](config/config.py#L28) |
| `/chart` | Статичний chart HTML | (static) | [runtime/http_server.py](runtime/http_server.py#L128-L136) |

## main

- Entry point: [app/main.py](app/main.py#L1-L59).
- Composition root: [app/composition.py](app/composition.py#L1-L140).

## Dataflow графи

### 1) tick → preview (якщо enabled)

```mermaid
flowchart LR
  T[tick_ts_ms] --> P[PreviewBuilder.on_tick]
  P --> C[OhlcvCache]
  C --> W[publish {NS}:ohlcv (preview)]
  C --> H[/api/ohlcv?mode=preview]
```

Джерела:
- PreviewBuilder і кеш: [runtime/preview_builder.py](runtime/preview_builder.py#L87-L173).
- Публікація preview у wire: [app/composition.py](app/composition.py#L375-L415).
- HTTP preview: [runtime/http_server.py](runtime/http_server.py#L81-L125).

### 2) history_provider → SQLite SSOT 1m final → derived_builder → HTF final → publish wire

```mermaid
flowchart LR
  H[HistoryProvider.fetch_1m_final] --> S[SQLite bars_1m_final]
  S --> D[build_htf_final]
  D --> H2[bars_htf_final]
  H2 --> W[publish {NS}:ohlcv (final)]
```

Джерела:
- Backfill: fetch + upsert 1m: [runtime/backfill.py](runtime/backfill.py#L70-L73).
- Warmup: fetch + upsert 1m: [runtime/warmup.py](runtime/warmup.py#L74-L77).
- SSOT інваріанти 1m/HTF: [store/schema.sql](store/schema.sql#L1-L75).
- HTF побудова: [store/derived_builder.py](store/derived_builder.py#L31-L123).
- HTF rebuild + publish: [runtime/rebuild_derived.py](runtime/rebuild_derived.py#L87-L206), publish: [runtime/rebuild_derived.py](runtime/rebuild_derived.py#L304-L307).

### 3) tail_guard → repair policy → republish watermark

```mermaid
flowchart LR
  TG[tail_guard audit] --> RP[repair_missing_1m]
  RP --> RB[rebuild_derived]
  RB --> RE[republish_tail + watermark]
```

Джерела:
- tail_guard flow: [runtime/tail_guard.py](runtime/tail_guard.py#L43-L190).
- republish watermark: [runtime/republish.py](runtime/republish.py#L15-L77), watermark зберігання: [store/schema.sql](store/schema.sql#L81-L87).

## Single Source of Truth (SSOT)

| SSOT | Що означає | Де визначено | Де enforced |
|---|---|---|---|
| Час = UTC epoch ms | всі ключові timestamp-и у ms | [core/validation/validator.py](core/validation/validator.py#L28-L33), [core/contracts/public/tick_v1.json](core/contracts/public/tick_v1.json#L1) | валідатор tick/ohlcv: [core/validation/validator.py](core/validation/validator.py#L28-L33) + gate tick units: [tools/exit_gates/gates/gate_tick_units.py](tools/exit_gates/gates/gate_tick_units.py#L1-L31) |
| OHLCV canonical keys | `open/high/low/close/volume` | [core/validation/validator.py](core/validation/validator.py#L75-L78) | валідатор HTF: [core/validation/validator.py](core/validation/validator.py#L218-L227) |
| NoMix (final) | один source на bar | [runtime/no_mix.py](runtime/no_mix.py#L8-L43) | SQLite CHECK + gate: [store/schema.sql](store/schema.sql#L19-L75), [tools/exit_gates/gates/gate_no_mix.py](tools/exit_gates/gates/gate_no_mix.py#L1-L54) |
| Watermark republish | TTL/skip на повторний publish | [runtime/republish.py](runtime/republish.py#L15-L77) | Redis key + gate: [runtime/republish.py](runtime/republish.py#L46-L66), [tools/exit_gates/gates/gate_republish_watermark.py](tools/exit_gates/gates/gate_republish_watermark.py#L1-L78) |
| Bucket boundary | `open_time` вирівняний, `close_time` inclusive | [core/time/buckets.py](core/time/buckets.py#L3-L69) | валідатор: [core/validation/validator.py](core/validation/validator.py#L81-L92), store CHECK: [store/schema.sql](store/schema.sql#L19-L22) |

## Інваріанти та enforcement

- **No silent fallback** для команд: будь-який invalid JSON / contract / unknown → `errors[]` + last_command error: [runtime/command_bus.py](runtime/command_bus.py#L181-L215).
- **Status pubsub size rail**: max payload + компактний snapshot: [runtime/status.py](runtime/status.py#L16-L95), enforcement: [runtime/status.py](runtime/status.py#L935-L948).
- **Preview rails**: late tick drop, sorted publish, misaligned tracking: [runtime/preview_builder.py](runtime/preview_builder.py#L87-L173), gate: [tools/exit_gates/gates/gate_preview_late_tick_drop.py](tools/exit_gates/gates/gate_preview_late_tick_drop.py#L1-L69).
- **Final-wire invariants**: close_time inclusive, source/history_agg, event_ts==close_time: [core/validation/validator.py](core/validation/validator.py#L178-L191), store CHECK: [store/schema.sql](store/schema.sql#L19-L75), gates: [tools/exit_gates/gates/gate_final_wire.py](tools/exit_gates/gates/gate_final_wire.py#L1-L56),
[tools/exit_gates/gates/gate_final_wire_from_store.py](tools/exit_gates/gates/gate_final_wire_from_store.py#L1-L78).

## Exit gates inventory

> Усі gate-скрипти: [tools/exit_gates/manifest.json](tools/exit_gates/manifest.json#L1-L20).

- gate_python_version — перевірка Python 3.7: [tools/exit_gates/gates/gate_python_version.py](tools/exit_gates/gates/gate_python_version.py#L1-L10).
- gate_xor_mode_scan — відсутність sim-імпортів у main/composition: [tools/exit_gates/gates/gate_xor_mode_scan.py](tools/exit_gates/gates/gate_xor_mode_scan.py#L1-L38).
- gate_no_duplicate_gate_runners — один runner/директорія gates: [tools/exit_gates/gates/gate_no_duplicate_gate_runners.py](tools/exit_gates/gates/gate_no_duplicate_gate_runners.py#L1-L62).
- gate_no_runtime_sims — немає runtime sim імпортів: [tools/exit_gates/gates/gate_no_runtime_sims.py](tools/exit_gates/gates/gate_no_runtime_sims.py#L1-L45).
- gate_tick_units — tick_ts_ms/snap_ts_ms у ms: [tools/exit_gates/gates/gate_tick_units.py](tools/exit_gates/gates/gate_tick_units.py#L1-L31).
- gate_preview_1m_boundaries — 1m open/close межі: [tools/exit_gates/gates/gate_preview_1m_boundaries.py](tools/exit_gates/gates/gate_preview_1m_boundaries.py#L1-L44).
- gate_preview_1m_geom — OHLC геометрія: [tools/exit_gates/gates/gate_preview_1m_geom.py](tools/exit_gates/gates/gate_preview_1m_geom.py#L1-L43).
- gate_preview_late_tick_drop — late tick drop + sorted publish: [tools/exit_gates/gates/gate_preview_late_tick_drop.py](tools/exit_gates/gates/gate_preview_late_tick_drop.py#L1-L69).
- gate_preview_multi_tf — перевірка multi‑TF у {NS}:ohlcv: [tools/exit_gates/gates/gate_preview_multi_tf.py](tools/exit_gates/gates/gate_preview_multi_tf.py#L1-L48).
- gate_fxcm_fsm_unit — FSM переходи/сталість: [tools/exit_gates/gates/gate_fxcm_fsm_unit.py](tools/exit_gates/gates/gate_fxcm_fsm_unit.py#L1-L31).
- gate_tick_fixtures_schema — валідація tick fixtures: [tools/exit_gates/gates/gate_tick_fixtures_schema.py](tools/exit_gates/gates/gate_tick_fixtures_schema.py#L1-L14).
- gate_history_tf_rail_scan — history TF=1m only: [tools/exit_gates/gates/gate_history_tf_rail_scan.py](tools/exit_gates/gates/gate_history_tf_rail_scan.py#L1-L39).
- gate_final_wire_from_store — final HTF invariants у store: [tools/exit_gates/gates/gate_final_wire_from_store.py](tools/exit_gates/gates/gate_final_wire_from_store.py#L1-L78).
- gate_tail_guard_marks_persist — marks persist/invalidate: [tools/exit_gates/gates/gate_tail_guard_marks_persist.py](tools/exit_gates/gates/gate_tail_guard_marks_persist.py#L1-L108).
- gate_tail_guard_repair_budget — repair budget exceeded guard: [tools/exit_gates/gates/gate_tail_guard_repair_budget.py](tools/exit_gates/gates/gate_tail_guard_repair_budget.py#L1-L61).
- gate_status_pubsub_size — status payload size rail: [tools/exit_gates/gates/gate_status_pubsub_size.py](tools/exit_gates/gates/gate_status_pubsub_size.py#L1-L16).
- gate_ui_candles_gap_scan — UI candles + gaps hooks: [tools/exit_gates/gates/gate_ui_candles_gap_scan.py](tools/exit_gates/gates/gate_ui_candles_gap_scan.py#L1-L23).
- gate_ui_gap_visualization_scan — insertWhitespace presence: [tools/exit_gates/gates/gate_ui_gap_visualization_scan.py](tools/exit_gates/gates/gate_ui_gap_visualization_scan.py#L1-L22).
- gate_ui_lite_no_last_payload_fallback — без fallback у UI Lite: [tools/exit_gates/gates/gate_ui_lite_no_last_payload_fallback.py](tools/exit_gates/gates/gate_ui_lite_no_last_payload_fallback.py#L1-L22).
- gate_calendar_gaps — CLI gate на gaps у trading time: [tools/exit_gates/gates/gate_calendar_gaps.py](tools/exit_gates/gates/gate_calendar_gaps.py#L1-L96).
- gate_final_wire — CLI gate на HTF final-wire: [tools/exit_gates/gates/gate_final_wire.py](tools/exit_gates/gates/gate_final_wire.py#L1-L56).
- gate_no_mix — CLI gate на NoMix у store: [tools/exit_gates/gates/gate_no_mix.py](tools/exit_gates/gates/gate_no_mix.py#L1-L54).
- gate_republish_watermark — CLI gate на watermark у status snapshot: [tools/exit_gates/gates/gate_republish_watermark.py](tools/exit_gates/gates/gate_republish_watermark.py#L1-L78).

## Дублікат‑ризики (дрейф логіки)

1) **`now_ms` / wall‑clock** у кількох місцях:
   - [runtime/status.py](runtime/status.py#L39-L40)
   - [runtime/warmup.py](runtime/warmup.py#L47-L82)
   - [runtime/backfill.py](runtime/backfill.py#L65-L84)
   - [runtime/tail_guard.py](runtime/tail_guard.py#L66-L211)
   - [runtime/republish.py](runtime/republish.py#L29)
   - [runtime/rebuild_derived.py](runtime/rebuild_derived.py#L202-L264)

   **Рекомендація SSOT:** єдиний helper у core/time/timestamps.py + централізована політика “market‑paused”.

2) **Boundary checks** дублюються у validator, store і gates:
   - [core/time/buckets.py](core/time/buckets.py#L3-L69)
   - [core/validation/validator.py](core/validation/validator.py#L81-L92)
   - [store/schema.sql](store/schema.sql#L19-L75)
   - [tools/exit_gates/gates/gate_calendar_gaps.py](tools/exit_gates/gates/gate_calendar_gaps.py#L1-L96)
   - [tools/exit_gates/gates/gate_final_wire.py](tools/exit_gates/gates/gate_final_wire.py#L1-L56)

   **Рекомендація SSOT:** тримати правила в core/time/buckets.py + core/validation/validator.py, а store/gates лише підтверджують.

3) **UI gap logic** дублюється у UI adapter + gates:
   - [ui_lite/static/chart_adapter.js](ui_lite/static/chart_adapter.js#L15-L86)
   - [tools/exit_gates/gates/gate_ui_gap_visualization_scan.py](tools/exit_gates/gates/gate_ui_gap_visualization_scan.py#L1-L22)

   **Рекомендація SSOT:** окремий policy‑модуль для gap‑рендеру з параметрами (cap/skip), щоб gates не дублювали логіку.
