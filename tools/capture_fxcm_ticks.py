from __future__ import annotations

import argparse
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.config import load_config
from core.env_loader import load_env
from core.time.timestamps import to_epoch_ms_utc
from core.validation.validator import ContractError
from runtime.fxcm_forexconnect import normalize_symbol


def _try_import_forexconnect() -> Tuple[Optional[Any], Optional[Any], Optional[str]]:
    try:
        from forexconnect import ForexConnect  # type: ignore[import]
        from forexconnect.common import Common  # type: ignore[import]

        return ForexConnect, Common, None
    except Exception as exc:  # noqa: BLE001
        return None, None, str(exc)


def _parse_symbols(value: str) -> List[str]:
    if not value:
        return []
    symbols = [normalize_symbol(item.strip()) for item in value.split(",") if item.strip()]
    return list(dict.fromkeys(symbols))


def _extract_tick_time(row: Any) -> Optional[Any]:
    for attr in ("time", "timestamp", "tick_time", "datetime", "date"):
        if hasattr(row, attr):
            return getattr(row, attr)
    return None


def _now_ms() -> int:
    return int(time.time() * 1000)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="XAUUSD")
    parser.add_argument("--duration_s", type=int, default=30)
    parser.add_argument("--out_dir", default="recordings/fxcm_ticks")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parents[1]
    load_env(root_dir)
    config = load_config()

    if config.fxcm_backend != "forexconnect":
        raise RuntimeError("fxcm_backend має бути forexconnect")
    if not config.fxcm_username or not config.fxcm_password:
        raise RuntimeError("FXCM credentials відсутні у .env.local/.env.prod")

    symbols = _parse_symbols(args.symbols)
    if not symbols:
        raise RuntimeError("symbols має бути непорожнім")

    duration_s = max(5, int(args.duration_s))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    captured_utc = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    tag = f"_{args.tag}" if args.tag else ""
    fname = f"fxcm_{'_'.join(symbols)}_{captured_utc}_{duration_s}s{tag}"
    jsonl_path = out_dir / f"{fname}.jsonl"
    meta_path = out_dir / f"{fname}.meta.json"

    ForexConnect, Common, err = _try_import_forexconnect()
    if ForexConnect is None or Common is None:
        raise RuntimeError(f"ForexConnect SDK недоступний: {err or 'unknown'}")

    fx = ForexConnect()
    fx.login(
        config.fxcm_username,
        config.fxcm_password,
        config.fxcm_host_url,
        config.fxcm_connection,
        "",
        "",
    )

    lock = threading.Lock()
    tick_ts_source = "snap"
    captured = 0

    def _write_line(payload: Dict[str, Any]) -> None:
        nonlocal captured
        line = json.dumps(payload, ensure_ascii=False)
        with lock:
            with jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            captured += 1

    offers_table = fx.get_table(fx.OFFERS)

    def _on_row(_listener: Any, _row_id: str, row: Any) -> None:
        nonlocal tick_ts_source
        instrument = getattr(row, "instrument", None)
        if not instrument:
            return
        symbol = normalize_symbol(str(instrument))
        if symbol not in symbols:
            return
        bid = getattr(row, "bid", None)
        ask = getattr(row, "ask", None)
        if bid is None or ask is None:
            return
        snap_ts_ms = _now_ms()
        raw_ts = _extract_tick_time(row)
        try:
            if raw_ts is None:
                tick_ts_ms = snap_ts_ms
                tick_ts_source = tick_ts_source if tick_ts_source in {"snap", "mixed"} else "mixed"
            else:
                tick_ts_ms = to_epoch_ms_utc(raw_ts)
                tick_ts_source = "offer_time" if tick_ts_source != "snap" else "mixed"
        except ContractError:
            raise RuntimeError("FXCM tick timestamp має бути epoch ms (не seconds/float)")

        payload = {
            "symbol": symbol,
            "bid": float(bid),
            "ask": float(ask),
            "mid": (float(bid) + float(ask)) / 2.0,
            "tick_ts_ms": int(tick_ts_ms),
            "snap_ts_ms": int(snap_ts_ms),
        }
        _write_line(payload)

    listener = Common.subscribe_table_updates(
        offers_table,
        on_add_callback=_on_row,
        on_change_callback=_on_row,
    )

    deadline = time.time() + duration_s
    try:
        while time.time() < deadline:
            time.sleep(0.2)
    finally:
        try:
            listener.unsubscribe()
        except Exception:
            pass
        try:
            fx.logout()
        except Exception:
            pass

    meta = {
        "schema": "tick_fixture_v1",
        "captured_utc": captured_utc,
        "duration_s": duration_s,
        "symbols": symbols,
        "tick_ts_source": tick_ts_source,
        "build_version": config.build_version,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OK: captured ticks={captured} -> {jsonl_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
