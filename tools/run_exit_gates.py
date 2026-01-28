from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _now_ts_ms() -> int:
    return int(time.time() * 1000)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _load_manifest(path: Path) -> List[Dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("manifest має бути списком")
    return data


def fail_direct_gate_run(gate_name: str) -> None:
    print(
        "FAIL: прямий запуск gate_*.py заборонено. "
        f"Використай python -m tools.exit_gates.gates.{gate_name} "
        "або python -m tools.run_exit_gates --out <dir> --manifest <path>"
    )
    sys.exit(1)


def _run_gate(entry: Dict[str, Any]) -> Dict[str, Any]:
    gate_id = str(entry.get("id"))
    module_name = str(entry.get("module"))
    fn_name = str(entry.get("fn"))
    started_ts = _now_ts_ms()
    ok = False
    details: Any = None
    try:
        module = importlib.import_module(module_name)
        fn = getattr(module, fn_name)
        ok, details = fn()
    except Exception as exc:  # noqa: BLE001
        ok = False
        details = f"виняток: {exc}"
    finished_ts = _now_ts_ms()
    return {
        "gate_id": gate_id,
        "ok": bool(ok),
        "details": details,
        "started_ts": started_ts,
        "finished_ts": finished_ts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parents[1]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))
    manifest_path = Path(args.manifest)
    out_root = Path(args.out)
    out_dir = out_root / _utc_stamp()
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = _load_manifest(manifest_path)
    results: List[Dict[str, Any]] = []

    for entry in manifest:
        result = _run_gate(entry)
        results.append(result)
        status = "OK" if result["ok"] else "FAIL"
        print(f"Gate {result['gate_id']}: {status}")

    results_path = out_dir / "results.json"
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    hashes: Dict[str, str] = {}
    hashes[str(manifest_path)] = _sha256(manifest_path)
    for entry in manifest:
        module_name = str(entry.get("module"))
        module_path = root_dir / Path(module_name.replace(".", "/") + ".py")
        if module_path.exists():
            hashes[str(module_path)] = _sha256(module_path)
    rules_path = root_dir / "docs" / "COPILOT_RULES.md"
    if rules_path.exists():
        hashes[str(rules_path)] = _sha256(rules_path)
    hashes_path = out_dir / "hashes.json"
    hashes_path.write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8")

    all_ok = all(item.get("ok") for item in results)
    if all_ok:
        print("OK: exit gates завершено")
        return 0
    print("FAIL: є gate з помилкою")
    return 1


if __name__ == "__main__":
    if __package__ is None:
        print("FAIL: запускай через python -m tools.run_exit_gates --out <dir> --manifest <path>")
        sys.exit(2)
    sys.exit(main())
