from __future__ import annotations

from pathlib import Path

from tools.exit_gates.gates import gate_no_runtime_sims

FORBIDDEN = (
    "runtime.tick_simulator",
    "runtime.ohlcv_preview_simulator",
    "runtime.history_sim_provider",
    "runtime.ohlcv_sim",
    "runtime.tick_sim",
)


def test_gate_no_runtime_sims_ok() -> None:
    ok, message = gate_no_runtime_sims.run()
    assert ok, message


def test_app_files_no_sim_imports() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in [root / "app" / "main.py", root / "app" / "composition.py"]:
        text = path.read_text(encoding="utf-8")
        assert all(pattern not in text for pattern in FORBIDDEN)


def test_scan_app_runtime_no_sim_imports() -> None:
    root = Path(__file__).resolve().parents[1]
    targets = [root / "app", root / "runtime"]
    for base in targets:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "runtime" in path.parts and "sim" in path.name:
                continue
            text = path.read_text(encoding="utf-8")
            assert all(pattern not in text for pattern in FORBIDDEN), str(path)
