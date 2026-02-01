# Runbook: Status payload v2 (для SMC)

## SSOT

- Контракт: `core/contracts/public/status_v2.json`.
- Snapshot: `{NS}:status:snapshot`.

## Ключові секції для SMC

- `market` — стан ринку.
- `history.ready` — готовність history.
- `command_bus.state` — стан command bus.
- `errors[]` — редактовані помилки (без деталей).
- `reconcile` / `republish` / `bootstrap` — `state` + `last_run_ts_ms`.

## Поля, на які **не можна** спиратися

- Будь‑які поля, яких немає у `status_v2.json`.
- Додаткові/нестандартизовані поля з legacy payloads.
- Деталі помилок (stack/validation text) — вони редактовані.

## Нотатка щодо legacy payloads

Якщо SMC надсилає старий формат (наприклад `type=fxcm_warmup`), конектор закономірно відхиляє такі повідомлення через `additionalProperties: false`. Перехід має бути на `commands_v1` envelope.
