# Exit Gates (SSOT)

## Єдина команда запуску

```
python tools/run_exit_gates.py --out reports/exit_gates --manifest tools/exit_gates/manifest.json
```

P1 календар (SSOT) — окремий manifest:

```
python tools/run_exit_gates.py --out reports/exit_gates --manifest tools/exit_gates/manifest_p1_calendar.json
```

## Proof-pack

Результати пишуться у:

```
reports/exit_gates/<YYYY-MM-DD_HHMMSS>/
  - results.json
  - hashes.json
```

## P7.1 gates

- gate_python_version
- gate_xor_mode_scan
- gate_no_duplicate_gate_runners

## Політика thin-wrapper

Допускаються лише ці wrapper-и для legacy CLI:

- tools/exit_gates/gate_calendar_gaps.py
- tools/exit_gates/gate_final_wire.py
- tools/exit_gates/gate_no_mix.py
- tools/exit_gates/gate_republish_watermark.py

Будь-який новий runner (наприклад run_exit_gates*.py, exit_gates_runner*.py) — FAIL.
