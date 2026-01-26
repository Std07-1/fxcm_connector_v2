from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def fixtures_dir() -> Path:
    return repo_root() / "tests" / "fixtures"


def fixture_path(name: str) -> Path:
    return fixtures_dir() / name
