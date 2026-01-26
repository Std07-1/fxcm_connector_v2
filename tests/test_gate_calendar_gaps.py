from __future__ import annotations

from pathlib import Path

from pytest import MonkeyPatch

from config.config import Config
from core.time.calendar import Calendar
from store.sqlite_store import SQLiteStore
from tests.fixtures.sim.history_sim_provider import HistorySimProvider
from tools.exit_gates.gates import gate_calendar_gaps


def test_gate_calendar_gaps_ok(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    db = tmp_path / "gate.sqlite"
    schema = Path(__file__).resolve().parents[1] / "store" / "schema.sql"
    store = SQLiteStore(db_path=db)
    store.init_schema(schema)

    fixed_now_ms = 1_736_980_000_000
    fixed_now_ms -= fixed_now_ms % 60_000

    test_config = Config(store_path=str(db))
    calendar = Calendar([], test_config.calendar_tag)
    provider = HistorySimProvider(calendar=calendar)
    start_ms = fixed_now_ms - 24 * 60 * 60 * 1000
    bars = provider.fetch_1m_final("XAUUSD", start_ms, fixed_now_ms, limit=2000)
    for bar in bars:
        bar["ingest_ts_ms"] = fixed_now_ms
    store.upsert_1m_final("XAUUSD", bars)

    monkeypatch.setattr(gate_calendar_gaps, "load_env", lambda _root: {})
    monkeypatch.setattr(gate_calendar_gaps, "load_config", lambda: test_config)
    monkeypatch.setattr(gate_calendar_gaps.time, "time", lambda: fixed_now_ms / 1000)
    monkeypatch.setattr(
        gate_calendar_gaps.sys,
        "argv",
        ["prog", "--symbol", "XAUUSD", "--hours", "24"],
    )

    code = gate_calendar_gaps.main()
    assert code == 0
