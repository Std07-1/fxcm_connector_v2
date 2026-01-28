from __future__ import annotations

from pathlib import Path

from core.time.sessions import load_calendar_overrides


def test_calendar_overrides_loading_for_tags() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ny = load_calendar_overrides(repo_root=repo_root, tag="fxcm_calendar_v1_ny")
    assert ny.tz_name == "America/New_York"
    assert ny.daily_break_minutes == 5

    utc = load_calendar_overrides(repo_root=repo_root, tag="fxcm_calendar_v1_utc_overrides")
    assert utc.tz_name == "UTC"
    assert utc.daily_break_minutes == 61
