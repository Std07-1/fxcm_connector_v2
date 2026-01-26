# Audit v6 — Exit gates inventory (read-only)

## Реєстр гейтів
Гейти визначені у manifest і запускаються через відповідні модулі:
- `gate_python_version`, `gate_xor_mode_scan`, `gate_no_duplicate_gate_runners`, `gate_no_runtime_sims`, `gate_tick_units`, `gate_preview_1m_boundaries`, `gate_preview_1m_geom`, `gate_preview_late_tick_drop`, `gate_fxcm_fsm_unit`, `gate_tick_fixtures_schema`,
  `gate_history_tf_rail_scan`, `gate_final_wire_from_store`, `gate_tail_guard_marks_persist`, `gate_tail_guard_repair_budget`, `gate_status_pubsub_size`, `gate_ui_candles_gap_scan`, `gate_ui_gap_visualization_scan`, `gate_ui_lite_no_last_payload_fallback` — [tools/exit_gates/manifest.json](tools/exit_gates/manifest.json#L1-L18).

## Run-only результати v6
- stdout bootstrap + exit gates збережено у [data/audit_v6/gates_stdout.txt](data/audit_v6/gates_stdout.txt).
- Exit codes зафіксовані у [data/audit_v6/notes.txt](data/audit_v6/notes.txt#L1-L6).
- Під час bootstrap зафіксовано падіння pytest (2 тести) — [data/audit_v6/gates_stdout.txt](data/audit_v6/gates_stdout.txt#L103-L104).
- One-shot запуск `python -m tools.exit_gates.gates.*` завершився помилками CLI аргументів (missing `--symbol`/`--tf`/`--tfs`) — [data/audit_v6/gates_stdout.txt](data/audit_v6/gates_stdout.txt#L186-L205).

## Примітка
- Деталізований аналіз PASS/FAIL береться лише з run-only stdout — [data/audit_v6/gates_stdout.txt](data/audit_v6/gates_stdout.txt).
