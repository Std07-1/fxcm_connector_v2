from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core.time.timestamps import to_epoch_ms_utc
from core.validation.validator import ContractError

REQUIRED_KEYS = {"symbol", "bid", "ask", "mid", "tick_ts_ms", "snap_ts_ms"}


def _validate_record(payload: Dict[str, Any]) -> None:
    missing = REQUIRED_KEYS - set(payload.keys())
    if missing:
        raise ContractError(f"відсутні ключі: {', '.join(sorted(missing))}")
    symbol = payload.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise ContractError("symbol має бути непорожнім рядком")
    for key in ("bid", "ask", "mid"):
        val = payload.get(key)
        if not isinstance(val, (int, float)):
            raise ContractError(f"{key} має бути числом")
    tick_ts_ms = payload.get("tick_ts_ms")
    snap_ts_ms = payload.get("snap_ts_ms")
    if not isinstance(tick_ts_ms, int):
        raise ContractError("tick_ts_ms має бути int")
    if not isinstance(snap_ts_ms, int):
        raise ContractError("snap_ts_ms має бути int")
    to_epoch_ms_utc(tick_ts_ms)
    to_epoch_ms_utc(snap_ts_ms)


def validate_jsonl(path: Path, max_lines: Optional[int] = None) -> Tuple[bool, str, int]:
    if not path.exists():
        return False, "файл не знайдено", 0
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if max_lines is not None:
        lines = lines[:max_lines]
    if not lines:
        return False, "файл порожній", 0
    count = 0
    try:
        for line in lines:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ContractError("рядок має бути JSON-об'єктом")
            _validate_record(payload)
            count += 1
    except (json.JSONDecodeError, ContractError) as exc:
        return False, str(exc), count
    return True, "OK", count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="in_path", required=True)
    parser.add_argument("--max_lines", type=int, default=0)
    args = parser.parse_args()

    max_lines = int(args.max_lines) if args.max_lines and args.max_lines > 0 else None
    ok, message, count = validate_jsonl(Path(args.in_path), max_lines=max_lines)
    if ok:
        print(f"OK: валідно рядків={count}")
        return 0
    print(f"FAIL: {message} (рядків={count})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
