# Runbook: SMC Command Integration (commands_v1)

## Канал керування

- Єдиний канал керування: `{NS}:commands`.
- `{NS}` береться з SSOT (config/config.py).

## CommandEnvelope (commands_v1)

SSOT контракт: `core/contracts/public/commands_v1.json`.

Обовʼязкові поля:

- `cmd`
- `req_id`
- `ts` (epoch ms)
- `args`

Приклад мінімального envelope:

```
{"cmd":"fxcm_reconcile_tail","req_id":"smc-001","ts":1706780000000,"args":{"symbols":["XAUUSD"],"lookback_minutes":20}}
```

## Auth (rolling режим)

Поля `auth` опційні, але можуть бути **required** залежно від режиму:

- `command_auth_enable=false` → auth ігнорується.
- `command_auth_enable=true`, `command_auth_required=false` → auth перевіряється, але не обовʼязковий.
- `command_auth_required=true` → без auth команда відхиляється.

Структура `auth`:

- `kid`
- `sig`
- `nonce`

Приклад envelope з auth:

```
{
  "cmd":"fxcm_reconcile_tail",
  "req_id":"smc-002",
  "ts":1706780000000,
  "args":{"symbols":["XAUUSD"],"lookback_minutes":20},
  "auth":{"kid":"k1","sig":"<HMAC_HEX>","nonce":"n-001"}
}
```

## Правила часу та anti-replay

- `ts` має бути в межах ±`command_auth_max_skew_ms`.
- `nonce` (або `req_id`) одноразовий у вікні `command_auth_replay_ttl_ms`.

## Політика retry

- `req_id` має бути унікальним для кожної команди.
- `nonce` має бути одноразовим; повтор у TTL → `replay_rejected`.

## Типові помилки інтеграції

- Надсилання legacy payload (наприклад `{"type":"fxcm_warmup", ...}`) → контракт відхиляється (`additionalProperties: false`).
- Відсутній `cmd/req_id/ts/args` → `contract_error`.
