# Runbook: Command HMAC auth (rolling)

## Мета

Увімкнути HMAC auth для команд з anti-replay, без зламу старих клієнтів.

## Rolling режим

- `command_auth_enable = false` → auth ігнорується.
- `command_auth_enable = true`, `command_auth_required = false` → auth перевіряється, але без auth команда приймається (rolling).
- `command_auth_required = true` → без auth команда відхиляється.

## Canonical підпис

Підпис рахується по канонічному JSON:

- `cmd`, `req_id`, `ts`, `args`, `kid`, `nonce`
- `sort_keys=true`, `separators=(',',':')`, UTF‑8
- `sig = HMAC-SHA256(secret, canonical_json)` (hex)

## Anti‑replay

Redis SET NX з TTL:

```
{NS}:cmd_replay:{kid}:{nonce}
```

Повторний `nonce`/`req_id` у TTL → `replay_rejected`.

## Налаштування (SSOT)

- `config/config.py`:
  - `command_auth_enable`
  - `command_auth_required`
  - `command_auth_max_skew_ms`
  - `command_auth_replay_ttl_ms`
  - `command_auth_allowed_kids`

## Секрети

Секрети **не** комітимо:

- `config/secrets_local.py` або `config/secrets_prod.py`

```
COMMAND_AUTH_DEFAULT_KID = "k1"
COMMAND_AUTH_SECRETS = {"k1": "<SECRET>"}
```

Або через env:

- `FXCM_HMAC_KID`
- `FXCM_HMAC_SECRET`

## Типові помилки

- `auth_failed` — відсутній/некоректний auth або підпис.
- `auth_ts_skew` — ts поза допустимим вікном.
- `replay_rejected` — повторний nonce/req_id у TTL.
