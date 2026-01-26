# Audit v6 — Delta vs P0..P5 (read-only)

Нижче: очікування (за P0..P5), факт (лише run-only дані) і наслідки.

## P0
- Очікування: bootstrap проходить без падінь; status snapshot валідний і без критичних помилок.
- Факт: bootstrap має падіння pytest (2 тести) — [data/audit_v6/gates_stdout.txt](data/audit_v6/gates_stdout.txt#L103-L104). У snapshot присутні `errors[]`/`degraded[]` — [data/audit_v6/status_snapshot.json](data/audit_v6/status_snapshot.json#L1).
- Ризик/наслідок: базовий gate незелений → будь-які P1–P5 висновки нестабільні.

## P1
- Очікування: tick feed без `tick_contract_reject` та з валідним allowlist.
- Факт: `tick_contract_reject` у `errors[]` і `degraded[]` — [data/audit_v6/status_snapshot.json](data/audit_v6/status_snapshot.json#L1).
- Ризик/наслідок: відкидання тіків → перекоси у preview/price та метриках.

## P2
- Очікування: preview rails чисті (boundaries/geom/late tick drop) і стабільні.
- Факт: preview gates у bootstrap пройшли — [data/audit_v6/gates_stdout.txt](data/audit_v6/gates_stdout.txt#L110-L112); snapshot містить активні лічильники preview — [data/audit_v6/status_snapshot.json](data/audit_v6/status_snapshot.json#L1).
- Ризик/наслідок: загальна стабільність залежить від вирішення P0/P1; інакше preview може бути некоректним під навантаженням.

## P3
- Очікування: final store (SQLite) має наповнені таблиці 1m/HTF.
- Факт: `bars_1m_final` і `bars_htf_final` існують, але count=0 — [data/audit_v6/store_tables.txt](data/audit_v6/store_tables.txt#L1-L6).
- Ризик/наслідок: final wire/republish немає що публікувати; аудит final не інформативний.

## P4
- Очікування: derived final збудований (rebuild не idle, є дані).
- Факт: `derived_rebuild` у snapshot — `state="idle"`, `last_run_ts_ms=0`; `ohlcv_final` по TF — нулі — [data/audit_v6/status_snapshot.json](data/audit_v6/status_snapshot.json#L1).
- Ризик/наслідок: відсутня derived-плита → downstream залежності не перевіряються.

## P5
- Очікування: репабліш працює за watermark/forced; gates запускаються штатно.
- Факт: `republish` у snapshot `state="idle"`, `published_batches=0`, `skipped_by_watermark=false` — [data/audit_v6/status_snapshot.json](data/audit_v6/status_snapshot.json#L1).
- Ризик/наслідок: P5 логіка не валідована у run-only циклі.

## Додаткові симптоми виконання гейтів
- One-shot запуск `python -m tools.exit_gates.gates.*` завершився помилками CLI аргументів (missing `--symbol`/`--tf`/`--tfs`) — [data/audit_v6/gates_stdout.txt](data/audit_v6/gates_stdout.txt#L186-L205).

## GO/NO‑GO
**NO‑GO** — блокери:
1) Падіння pytest у bootstrap (2 тести) — [data/audit_v6/gates_stdout.txt](data/audit_v6/gates_stdout.txt#L103-L104).
2) One-shot gates падають через відсутні CLI аргументи — [data/audit_v6/gates_stdout.txt](data/audit_v6/gates_stdout.txt#L186-L205).
3) Final store порожній (count=0) — [data/audit_v6/store_tables.txt](data/audit_v6/store_tables.txt#L1-L8).
