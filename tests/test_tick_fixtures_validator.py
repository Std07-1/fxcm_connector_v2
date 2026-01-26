from __future__ import annotations

import json
from pathlib import Path

from core.fixtures_path import fixture_path
from tools.validate_tick_fixtures import validate_jsonl


def test_tick_fixtures_ok() -> None:
    fixture = fixture_path("ticks_sample_fxcm.jsonl")
    ok, message, count = validate_jsonl(fixture)
    assert ok, message
    assert count >= 20


def test_tick_fixtures_fail_seconds(tmp_path: Path) -> None:
    path = tmp_path / "bad_seconds.jsonl"
    payload = {
        "symbol": "XAUUSD",
        "bid": 1.0,
        "ask": 1.1,
        "mid": 1.05,
        "tick_ts_ms": 1_700_000_000,
        "snap_ts_ms": 1_700_000_001,
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    ok, message, _ = validate_jsonl(path)
    assert not ok
    assert "epoch ms" in message


def test_tick_fixtures_fail_float(tmp_path: Path) -> None:
    path = tmp_path / "bad_float.jsonl"
    payload = {
        "symbol": "XAUUSD",
        "bid": 1.0,
        "ask": 1.1,
        "mid": 1.05,
        "tick_ts_ms": 1_700_000_000_000.5,
        "snap_ts_ms": 1_700_000_000_001.0,
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    ok, message, _ = validate_jsonl(path)
    assert not ok
    assert "int" in message


def test_tick_fixtures_fail_missing_field(tmp_path: Path) -> None:
    path = tmp_path / "bad_missing.jsonl"
    payload = {
        "symbol": "XAUUSD",
        "bid": 1.0,
        "ask": 1.1,
        "mid": 1.05,
        "tick_ts_ms": 1_700_000_000_000,
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    ok, message, _ = validate_jsonl(path)
    assert not ok
    assert "відсутні ключі" in message
