from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Iterable, Set, Tuple

from config.config import load_config
from runtime.fxcm_forexconnect import _try_import_forexconnect, denormalize_symbol


def _extract_keys(row: Any) -> Set[str]:
    if isinstance(row, dict):
        return {str(k) for k in row.keys()}
    if hasattr(row, "_fields"):
        try:
            return {str(k) for k in row._fields}
        except Exception:
            pass
    try:
        return {str(k) for k in vars(row).keys()}
    except Exception:
        pass
    keys: Set[str] = set()
    for name in dir(row):
        if name.startswith("_"):
            continue
        try:
            value = getattr(row, name)
        except Exception:
            continue
        if callable(value):
            continue
        keys.add(str(name))
    return keys


def _has_any(keys_lower: Iterable[str], needle: str) -> bool:
    return any(needle in key for key in keys_lower)


def run() -> Tuple[bool, str]:
    config = load_config()
    if config.fxcm_backend != "forexconnect":
        return True, "SKIP: fxcm_backend != forexconnect (gate не застосовується)"
    if not config.fxcm_username or not config.fxcm_password:
        return True, "SKIP: fxcm_secrets_missing"
    fx_class, err = _try_import_forexconnect()
    if fx_class is None:
        return True, f"SKIP: fxcm_sdk_missing: {err or 'unknown'}"
    if not config.fxcm_symbols:
        return False, "FAIL: fxcm_symbols порожній"

    symbol = config.fxcm_symbols[0]
    instrument = denormalize_symbol(symbol)

    now_ms = int(time.time() * 1000)
    end_ms = now_ms - 60_000
    start_ms = end_ms - 10 * 60_000 + 1
    if end_ms <= start_ms:
        return False, "FAIL: некоректний діапазон для history smoke"

    start_dt = datetime.fromtimestamp(start_ms / 1000.0, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(end_ms / 1000.0, tz=timezone.utc)

    fx = fx_class()
    try:
        fx.login(
            config.fxcm_username,
            config.fxcm_password,
            config.fxcm_host_url,
            config.fxcm_connection,
            "",
            "",
        )
        history = fx.get_history(instrument, "m1", start_dt, end_dt)
        rows = list(history) if history is not None else []
    except Exception as exc:  # noqa: BLE001
        return False, f"FAIL: fxcm history fetch failed: {exc}"
    finally:
        try:
            fx.logout()
        except Exception:
            pass

    if not rows:
        return False, "FAIL: історичних рядків=0"
    if len(rows) not in (10, 11):
        return False, f"FAIL: історичних рядків={len(rows)} очікується 10 або 11 (інклюзивні межі)"

    keys = _extract_keys(rows[0])
    if not keys:
        return False, "FAIL: порожній набір ключів у history рядку"
    keys_lower = {key.lower() for key in keys}

    time_ok = any(
        key in keys_lower
        for key in {
            "date",
            "time",
            "timestamp",
            "open_time",
            "open_time_utc",
            "open_time_ms",
        }
    )
    bid_ok = _has_any(keys_lower, "bid")
    ask_ok = _has_any(keys_lower, "ask")
    vol_ok = _has_any(keys_lower, "vol")

    if not (time_ok and bid_ok and ask_ok and vol_ok):
        return False, f"FAIL: ключі не відповідають (time/bid/ask/volume). keys={sorted(keys)}"

    return True, f"OK: історичних рядків={len(rows)} ключі=ok"
