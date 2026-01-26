from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, cast
from urllib.request import urlopen

import redis
from websockets.legacy.client import connect

from config.config import Config


def _read_debug(url: str) -> Dict[str, Any]:
    with urlopen(url, timeout=3) as resp:
        raw = resp.read()
    return cast(Dict[str, Any], json.loads(raw.decode("utf-8")))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_payload(symbol: str, tf: str, mode: str, base_ts: int, count: int) -> Dict[str, Any]:
    bars: List[Dict[str, Any]] = []
    aligned = base_ts - (base_ts % 60_000)
    is_final = mode == "final"
    source = "history_agg" if is_final else "stream"
    for i in range(count):
        open_time_ms = aligned + (i * 60_000)
        close_time_ms = open_time_ms + 60_000 - 1
        bar: Dict[str, Any] = {
            "open_time": open_time_ms,
            "close_time": close_time_ms,
            "open": 1.0 + i,
            "high": 1.5 + i,
            "low": 0.5 + i,
            "close": 1.2 + i,
            "volume": 10.0,
            "complete": is_final,
            "synthetic": False,
            "source": source,
        }
        if is_final:
            bar["event_ts"] = close_time_ms
        bars.append(bar)
    return {
        "symbol": symbol,
        "tf": tf,
        "source": source,
        "complete": is_final,
        "synthetic": False,
        "ts": base_ts,
        "bars": bars,
    }


def _publish(redis_client: redis.Redis, channel: str, payload: Dict[str, Any]) -> None:
    redis_client.publish(channel, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _validate_bars(bars: List[Dict[str, Any]]) -> None:
    if not bars:
        raise RuntimeError("snapshot bars порожні")
    for bar in bars:
        time_s = int(bar.get("time", 0))
        if time_s <= 0:
            raise RuntimeError("snapshot bar.time <= 0")


async def _ws_flow(
    ws_url: str,
    redis_client: redis.Redis,
    channel: str,
    symbol: str,
    tf: str,
    mode: str,
    publish_after: Dict[str, Any],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"snapshot": None, "bar": None}
    async with connect(ws_url, open_timeout=3) as ws:
        await ws.send(json.dumps({"type": "subscribe", "symbol": symbol, "tf": tf, "mode": mode}))
        raw = await asyncio.wait_for(ws.recv(), timeout=3)
        snapshot = json.loads(raw)
        if snapshot.get("type") != "snapshot":
            raise RuntimeError("перший пакет не snapshot")
        _validate_bars(snapshot.get("bars", []))
        result["snapshot"] = snapshot

        _publish(redis_client, channel, publish_after)

        bar_msg = None
        for _ in range(5):
            raw_bar = await asyncio.wait_for(ws.recv(), timeout=3)
            payload = json.loads(raw_bar)
            if payload.get("type") == "bar":
                bar_msg = payload
                break
        if bar_msg is None:
            raise RuntimeError("bar повідомлення не отримано")
        bar = bar_msg.get("bar", {})
        if int(bar.get("time", 0)) <= 0:
            raise RuntimeError("bar.time <= 0")
        result["bar"] = bar_msg
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ns", default="fxcm_local")
    parser.add_argument("--redis-host", default="127.0.0.1")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--out-dir", default="data/audit_v3")
    parser.add_argument("--prefix", default="p61_local")
    parser.add_argument("--mode", default="preview")
    args = parser.parse_args()

    config = Config(ns=args.ns, commands_enabled=False)
    host = config.ui_lite_host
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    port = config.ui_lite_port

    http_url = "http://{0}:{1}/debug".format(host, port)
    ws_url = "ws://{0}:{1}".format(host, port)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    debug_before = _read_debug(http_url)

    symbol = "XAUUSD"
    tf = "1m"
    mode = args.mode
    base_ts = int(time.time() * 1000)

    redis_client = redis.Redis(host=args.redis_host, port=args.redis_port, decode_responses=True)
    channel = config.ch_ohlcv()

    publish_before = _build_payload(symbol, tf, mode, base_ts, 2)
    _publish(redis_client, channel, publish_before)
    time.sleep(0.3)

    loop = asyncio.get_event_loop()
    publish_after = _build_payload(symbol, tf, mode, base_ts + 120_000, 1)
    ws_result = loop.run_until_complete(_ws_flow(ws_url, redis_client, channel, symbol, tf, mode, publish_after))

    debug_after = _read_debug(http_url)

    if int(debug_after.get("last_payload_ts_ms", 0)) <= 0:
        raise RuntimeError("/debug last_payload_ts_ms <= 0")
    if int(debug_after.get("last_payload_open_time_ms", 0)) <= 0:
        raise RuntimeError("/debug last_payload_open_time_ms <= 0")
    if int(debug_after.get("last_payload_close_time_ms", 0)) <= 0:
        raise RuntimeError("/debug last_payload_close_time_ms <= 0")
    if debug_after.get("last_payload_mode") not in ("preview", "final"):
        raise RuntimeError("/debug last_payload_mode не preview/final")
    if int(debug_after.get("last_ui_bar_time_s", 0)) <= 0:
        raise RuntimeError("/debug last_ui_bar_time_s <= 0")
    if int(debug_after.get("last_ring_size", 0)) <= 0:
        raise RuntimeError("/debug last_ring_size <= 0")

    _write_json(out_dir / (args.prefix + ".debug_before.json"), debug_before)
    _write_json(out_dir / (args.prefix + ".debug_after.json"), debug_after)
    _write_json(out_dir / (args.prefix + ".publish_before.json"), publish_before)
    _write_json(out_dir / (args.prefix + ".publish_after.json"), publish_after)
    _write_json(out_dir / (args.prefix + ".snapshot.json"), ws_result["snapshot"])
    _write_json(out_dir / (args.prefix + ".bar.json"), ws_result["bar"])

    print("OK: UI Lite WS smoke")
    print("debug_before:", (out_dir / (args.prefix + ".debug_before.json")).resolve())
    print("debug_after:", (out_dir / (args.prefix + ".debug_after.json")).resolve())


if __name__ == "__main__":
    main()
