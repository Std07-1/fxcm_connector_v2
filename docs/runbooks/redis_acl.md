# Runbook: Redis ACL (Layer A)

## Мета

Забезпечити transport‑level захист команд через Redis ACL:

- UI користувач — **read‑only**, без PUBLISH.
- SMC користувач — PUBLISH **лише** на `{NS}:commands`, read на `{NS}:status*` і `{NS}:ohlcv*`.
- connector користувач — доступ лише в межах `{NS}:*`.

## Передумови

- Redis 6+ (ACL підтримка). Для channel patterns (`&pattern`) потрібен Redis 7+.
- `{NS}` — namespace з `config/config.py`.

## ACL команди (Redis 7+ з channel patterns)

### UI (read‑only)

```
ACL SETUSER ui on >UI_PASS ~* +ping +get +mget +subscribe +psubscribe +client -publish
ACL SETUSER ui resetchannels &{NS}:*  # дозволити лише канали NS
```

### SMC (publish тільки commands)

```
ACL SETUSER smc on >SMC_PASS ~* +ping +publish +get +mget +subscribe +psubscribe
ACL SETUSER smc resetchannels &{NS}:commands &{NS}:status* &{NS}:ohlcv*
```

### Connector (full in‑NS)

```
ACL SETUSER connector on >CONNECTOR_PASS ~* +@all
ACL SETUSER connector resetchannels &{NS}:*
```

## Якщо Redis < 7 (без channel patterns)

- Використати **окремий Redis інстанс** для control‑plane (commands/status/ohlcv).
- Або мережевий периметр + окремі користувачі без доступу “ззовні”.

## Операційні інваріанти

### Перевірка ACL

```
ACL LIST
ACL GETUSER ui
ACL GETUSER smc
ACL GETUSER connector
```

### Перевірка каналів/підписок

```
PUBSUB CHANNELS
PUBSUB NUMSUB {NS}:commands {NS}:status {NS}:ohlcv
```

### Smoke‑перевірки

- UI користувач: `PUBLISH` має бути заборонено.
- SMC користувач: `PUBLISH {NS}:commands ...` дозволено, `PUBLISH {NS}:status ...` заборонено.
- Connector: публікації у `{NS}:*` дозволено.

## Нотатки

- Runbook не містить внутрішніх allowlist/контрактів — лише transport‑рівень.
