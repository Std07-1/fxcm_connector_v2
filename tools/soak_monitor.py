from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import redis

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.config import Config  # noqa: E402
from core.env_loader import load_env  # noqa: E402
from core.time.buckets import TF_TO_MS  # noqa: E402


def _parse_open_time_ms(bar: Dict[str, Any]) -> Optional[int]:
    open_time = bar.get("open_time_ms")
    if open_time is None:
        open_time = bar.get("open_time")
    if open_time is None:
        return None
    try:
        return int(open_time)
    except (TypeError, ValueError):
        return None


def _parse_tf(payload: Dict[str, Any], bar: Dict[str, Any]) -> Optional[str]:
    tf = payload.get("tf")
    if not tf:
        tf = bar.get("tf")
    if not tf:
        return None
    return str(tf)


def _parse_symbol(payload: Dict[str, Any], bar: Dict[str, Any]) -> Optional[str]:
    symbol = payload.get("symbol")
    if not symbol:
        symbol = bar.get("symbol")
    if not symbol:
        return None
    return str(symbol)


def _mode_from_payload(payload: Dict[str, Any], bar: Dict[str, Any]) -> str:
    complete = bar.get("complete")
    if complete is None:
        complete = payload.get("complete", False)
    return "final" if bool(complete is True) else "preview"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_report_payload(
    summary: Dict[str, Any],
    ns: str,
    symbol: str,
    tf: str,
    mode: str,
) -> Dict[str, Any]:
    payload = dict(summary)
    payload["ns"] = ns
    payload["symbol"] = symbol
    payload["tf"] = tf
    payload["mode"] = mode
    return payload


def _monitor(
    redis_client: redis.Redis,
    channel: str,
    duration_s: int,
    tf_filter: Optional[str],
    symbol_filter: Optional[str],
    mode_filter: Optional[str],
    max_gap_bars: int,
) -> Tuple[int, Dict[str, Any]]:
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(channel)
    started = time.time()

    max_open_by_key: Dict[Tuple[str, str, str], int] = {}
    last_bar_by_open_time: Dict[Tuple[str, str, str], Dict[int, Tuple[float, float, float, float, float, bool]]] = {}
    identical_dups = 0
    same_open_time_updates = 0
    past_mutations = 0
    misaligned = 0
    invalid_bars = 0
    bars_total = 0
    last_open_time_ms = 0

    try:
        while True:
            if duration_s > 0 and time.time() - started >= duration_s:
                break
            message = pubsub.get_message(timeout=1.0)
            if not message:
                continue
            if message.get("type") != "message":
                continue
            data = message.get("data")
            raw = data.decode("utf-8") if isinstance(data, bytes) else str(data)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            bars = payload.get("bars", [])
            if not isinstance(bars, list):
                continue
            for bar in bars:
                if not isinstance(bar, dict):
                    continue
                open_time_ms = _parse_open_time_ms(bar)
                if open_time_ms is None:
                    invalid_bars += 1
                    continue
                tf = _parse_tf(payload, bar)
                if tf is None or tf not in TF_TO_MS:
                    invalid_bars += 1
                    continue
                if tf_filter and tf != tf_filter:
                    continue
                symbol = _parse_symbol(payload, bar)
                if symbol is None:
                    invalid_bars += 1
                    continue
                if symbol_filter and symbol != symbol_filter:
                    continue
                mode = _mode_from_payload(payload, bar)
                if mode_filter and mode != mode_filter:
                    continue
                key = (symbol, tf, mode)
                bars_total += 1
                last_open_time_ms = open_time_ms

                step = TF_TO_MS[tf]
                if open_time_ms % step != 0:
                    misaligned += 1
                max_seen = max_open_by_key.get(key, 0)
                if open_time_ms > max_seen:
                    max_open_by_key[key] = open_time_ms
                    max_seen = open_time_ms
                sealed_threshold_ms = max_seen - step
                by_open = last_bar_by_open_time.setdefault(key, {})
                open_val = float(bar.get("open", 0.0))
                high_val = float(bar.get("high", 0.0))
                low_val = float(bar.get("low", 0.0))
                close_val = float(bar.get("close", 0.0))
                volume_val = float(bar.get("volume", 0.0)) if "volume" in bar else 0.0
                complete_val = bool(bar.get("complete") is True)
                cur = (open_val, high_val, low_val, close_val, volume_val, complete_val)
                prev = by_open.get(open_time_ms)
                if prev is None:
                    by_open[open_time_ms] = cur
                    continue
                if prev == cur:
                    identical_dups += 1
                else:
                    if open_time_ms <= sealed_threshold_ms:
                        past_mutations += 1
                    else:
                        same_open_time_updates += 1
                    by_open[open_time_ms] = cur
    finally:
        try:
            pubsub.close()
        except Exception:
            pass

    summary = {
        "channel": channel,
        "duration_s": duration_s,
        "bars_total": bars_total,
        "identical_dups": identical_dups,
        "same_open_time_updates": same_open_time_updates,
        "past_mutations": past_mutations,
        "misaligned": misaligned,
        "invalid_bars": invalid_bars,
        "last_open_time_ms": last_open_time_ms,
    }
    exit_code = 0 if past_mutations == 0 and misaligned == 0 else 2
    return exit_code, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ns", default="fxcm_local")
    parser.add_argument("--redis-host", default="127.0.0.1")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--duration_s", type=int, default=120)
    parser.add_argument("--duration-s", dest="duration_s", type=int)
    parser.add_argument("--tf", default="1m")
    parser.add_argument("--symbol", default="")
    parser.add_argument("--mode", default="preview")
    parser.add_argument("--max-gap-bars", type=int, default=0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parents[1]
    load_env(root_dir)

    config = Config(ns=args.ns, commands_enabled=False)
    redis_client = redis.Redis(host=args.redis_host, port=args.redis_port, decode_responses=True)

    tf_filter = args.tf if args.tf else None
    symbol_filter = args.symbol if args.symbol else None
    mode_filter = args.mode if args.mode else None
    if mode_filter not in (None, "preview", "final"):
        raise SystemExit("mode має бути preview або final")
    duration_s = int(args.duration_s) if args.duration_s is not None else 120
    exit_code, summary = _monitor(
        redis_client,
        config.ch_ohlcv(),
        duration_s=max(0, duration_s),
        tf_filter=tf_filter,
        symbol_filter=symbol_filter,
        mode_filter=mode_filter,
        max_gap_bars=max(0, int(args.max_gap_bars)),
    )

    print("Soak monitor завершено")
    print(
        "bars_total={bars_total} identical_dups={identical_dups} same_open_time_updates={same_open_time_updates} "
        "past_mutations={past_mutations} misaligned={misaligned} last_open_time_ms={last_open_time_ms} "
        "invalid_bars={invalid_bars}".format(**summary)
    )

    ts_label = str(int(time.time() * 1000))
    out_path = Path(args.out) if args.out else Path("reports") / "soak" / f"{ts_label}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report_payload = build_report_payload(
        summary,
        ns=args.ns,
        symbol=symbol_filter or "",
        tf=tf_filter or "",
        mode=mode_filter or "",
    )
    _write_json(out_path, report_payload)
    print("Звіт збережено:", out_path.resolve())

    if exit_code != 0:
        print("FAIL: past_mutations або misaligned > 0", file=sys.stderr)
    else:
        print("OK: past_mutations=0 та misaligned=0")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
