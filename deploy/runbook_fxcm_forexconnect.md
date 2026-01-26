# Runbook: FXCM ForexConnect

## 1) Вимоги

- ForexConnect SDK (офіційний пакет FXCM).
- Python 3.7 + venv.
- Redis доступний локально або у мережі.

## 2) Розміщення SDK

### Windows

- Додай шлях до DLL FXCM у `PATH`.
- Переконайся, що `forexconnect.py` доступний у `PYTHONPATH`.

### Linux

- Розмісти `.so` файли SDK у системному шляху (`LD_LIBRARY_PATH`).
- Додай каталог SDK у `PYTHONPATH`.

## 3) Secrets (локально/прод)

- Створи `config/secrets_local.py` або `config/secrets_prod.py`.
- Заповни:
  - `FXCM_USERNAME`
  - `FXCM_PASSWORD`

## 4) Профілі

- Для профілю створи `config/profile_local.py` або `config/profile_prod.py`.
- У `PROFILE_OVERRIDES` задай NS/Redis/порти (несекретні).

## 5) Запуск

```bash
# локально
AIONE_PROFILE=local
python -m app.main
```

## 6) Healthchecks

- `redis-cli GET {NS}:status:snapshot`
- `curl http://127.0.0.1:9200/metrics`
- `curl http://127.0.0.1:8089/debug` (UI Lite, якщо увімкнено)

## 7) Exit Gate P7

- Offline:
  - `powershell -ExecutionPolicy Bypass -File tools/audit/run_exit_gate_p7.ps1 -Mode offline`
- Online (лише з SDK+креденшалами):
  - `powershell -ExecutionPolicy Bypass -File tools/audit/run_exit_gate_p7.ps1 -Mode online`
