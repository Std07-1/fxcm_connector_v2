# Audit v5 — Exit Gates Inventory (as‑is)

Дата: 2026-01-22
Режим: read-only discovery

Джерело переліку: [tools/exit_gates/manifest.json](tools/exit_gates/manifest.json#L1-L20)

## Gates (core)

- gate_python_version — перевірка Python 3.7. Вхід: sys.version. Вихід: PASS/FAIL. [tools/exit_gates/gates/gate_python_version.py](tools/exit_gates/gates/gate_python_version.py#L1-L10)
- gate_xor_mode_scan — заборона sim‑імпортів у main/composition. Вхід: app/main.py, app/composition.py. [tools/exit_gates/gates/gate_xor_mode_scan.py](tools/exit_gates/gates/gate_xor_mode_scan.py#L1-L38)
- gate_no_duplicate_gate_runners — відсутність дубль runner/gates директорій. Вхід: tree. [tools/exit_gates/gates/gate_no_duplicate_gate_runners.py](tools/exit_gates/gates/gate_no_duplicate_gate_runners.py#L1-L62)
- gate_no_runtime_sims — відсутність runtime sim імпортів. Вхід: app/, runtime/. [tools/exit_gates/gates/gate_no_runtime_sims.py](tools/exit_gates/gates/gate_no_runtime_sims.py#L1-L45)
- gate_tick_units — tick_ts_ms/snap_ts_ms у ms на fixtures. Вхід: tests/fixtures/ticks_sample.jsonl. [tools/exit_gates/gates/gate_tick_units.py](tools/exit_gates/gates/gate_tick_units.py#L1-L31)
- gate_preview_1m_boundaries — preview 1m boundaries на fixture. Вхід: tests/fixtures/ohlcv_preview_1m_sample.json. [tools/exit_gates/gates/gate_preview_1m_boundaries.py](tools/exit_gates/gates/gate_preview_1m_boundaries.py#L1-L44)
- gate_preview_1m_geom — OHLC geometry на fixture. Вхід: tests/fixtures/ohlcv_preview_1m_sample.json. [tools/exit_gates/gates/gate_preview_1m_geom.py](tools/exit_gates/gates/gate_preview_1m_geom.py#L1-L43)
- gate_preview_late_tick_drop — late‑tick drop + sorted publish. Вхід: tests/fixtures/ticks_out_of_order_boundary.jsonl. [tools/exit_gates/gates/gate_preview_late_tick_drop.py](tools/exit_gates/gates/gate_preview_late_tick_drop.py#L1-L69)
- gate_fxcm_fsm_unit — FSM переходи. Вхід: runtime/fxcm/fsm. [tools/exit_gates/gates/gate_fxcm_fsm_unit.py](tools/exit_gates/gates/gate_fxcm_fsm_unit.py#L1-L31)
- gate_tick_fixtures_schema — tick fixtures schema. Вхід: tests/fixtures/ticks_sample_fxcm.jsonl. [tools/exit_gates/gates/gate_tick_fixtures_schema.py](tools/exit_gates/gates/gate_tick_fixtures_schema.py#L1-L14)
- gate_history_tf_rail_scan — history TF=1m only. Вхід: runtime/, fxcm/. [tools/exit_gates/gates/gate_history_tf_rail_scan.py](tools/exit_gates/gates/gate_history_tf_rail_scan.py#L1-L39)
- gate_final_wire_from_store — HTF final invariants у store. Вхід: temp SQLite. [tools/exit_gates/gates/gate_final_wire_from_store.py](tools/exit_gates/gates/gate_final_wire_from_store.py#L1-L78)
- gate_tail_guard_marks_persist — marks persist/invalidate. Вхід: SQLite temp. [tools/exit_gates/gates/gate_tail_guard_marks_persist.py](tools/exit_gates/gates/gate_tail_guard_marks_persist.py#L1-L108)
- gate_tail_guard_repair_budget — repair budget exceeded. Вхід: tests/fixtures/sim/history_sim_provider. [tools/exit_gates/gates/gate_tail_guard_repair_budget.py](tools/exit_gates/gates/gate_tail_guard_repair_budget.py#L1-L61)
- gate_status_pubsub_size — status size rail у code. Вхід: runtime/status.py. [tools/exit_gates/gates/gate_status_pubsub_size.py](tools/exit_gates/gates/gate_status_pubsub_size.py#L1-L16)
- gate_ui_candles_gap_scan — UI candles + gaps hooks. Вхід: ui_lite/static/*. [tools/exit_gates/gates/gate_ui_candles_gap_scan.py](tools/exit_gates/gates/gate_ui_candles_gap_scan.py#L1-L23)
- gate_ui_gap_visualization_scan — insertWhitespace presence. Вхід: ui_lite/static/chart_adapter.js. [tools/exit_gates/gates/gate_ui_gap_visualization_scan.py](tools/exit_gates/gates/gate_ui_gap_visualization_scan.py#L1-L22)
- gate_ui_lite_no_last_payload_fallback — без fallback у WS handler. Вхід: ui_lite/server.py. [tools/exit_gates/gates/gate_ui_lite_no_last_payload_fallback.py](tools/exit_gates/gates/gate_ui_lite_no_last_payload_fallback.py#L1-L22)
- gate_preview_multi_tf — отримання multi‑TF у Redis. Вхід: Redis {NS}:ohlcv. [tools/exit_gates/gates/gate_preview_multi_tf.py](tools/exit_gates/gates/gate_preview_multi_tf.py#L1-L48)

## CLI wrappers (tools/exit_gates/*.py)

- gate_calendar_gaps CLI wrapper: [tools/exit_gates/gate_calendar_gaps.py](tools/exit_gates/gate_calendar_gaps.py#L1-L11)
- gate_final_wire CLI wrapper: [tools/exit_gates/gate_final_wire.py](tools/exit_gates/gate_final_wire.py#L1-L11)
- gate_no_mix CLI wrapper: [tools/exit_gates/gate_no_mix.py](tools/exit_gates/gate_no_mix.py#L1-L11)
- gate_republish_watermark CLI wrapper: [tools/exit_gates/gate_republish_watermark.py](tools/exit_gates/gate_republish_watermark.py#L1-L11)
