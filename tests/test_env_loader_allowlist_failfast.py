from __future__ import annotations

from pathlib import Path

import pytest

from core.env_loader import load_env


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_env_loader_allowlist_failfast(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    _write(root / ".env", "AI_ONE_ENV_FILE=.env.local\n")
    _write(root / ".env.local", "FXCM_USERNAME=demo\nUNKNOWN_KEY=1\n")
    monkeypatch.delenv("AI_ONE_ENV_FILE", raising=False)
    with pytest.raises(RuntimeError):
        load_env(root)
