from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SampleReport:
    path: str
    bytes_utf8: int
    top_level_keys: int
    section_bytes: Dict[str, int]
    top_sections: List[Tuple[str, int]]
    errors_count: int
    errors_by_code: Dict[str, int]
    errors_duplicates: int
    tail_guard_sizes: Dict[str, int]
    ohlcv_final_duplicate: Optional[bool]


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    raw = ""
    for enc in ("utf-8", "utf-16", "utf-16-le"):
        try:
            raw = path.read_text(encoding=enc).strip()
            break
        except Exception:
            raw = ""
            continue
    if not raw:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if isinstance(data, dict):
        return data
    return None


def _json_bytes(obj: Any) -> int:
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return len(data.encode("utf-8"))


def _percentile(values: List[int], p: int) -> Optional[int]:
    if not values:
        return None
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)
    values_sorted = sorted(values)
    idx = int(round((p / 100.0) * (len(values_sorted) - 1)))
    return int(values_sorted[idx])


def _errors_stats(errors: Any) -> Tuple[int, Dict[str, int], int]:
    if not isinstance(errors, list):
        return 0, {}, 0
    by_code: Dict[str, int] = {}
    seen: Dict[str, int] = {}
    duplicates = 0
    for entry in errors:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code", ""))
        if not code:
            continue
        by_code[code] = by_code.get(code, 0) + 1
        context = entry.get("context")
        key = json.dumps({"code": code, "context": context}, ensure_ascii=False, separators=(",", ":"))
        if key in seen:
            duplicates += 1
        seen[key] = seen.get(key, 0) + 1
    return len(errors), by_code, duplicates


def _tail_guard_sizes(tail_guard: Any) -> Dict[str, int]:
    sizes: Dict[str, int] = {}
    if not isinstance(tail_guard, dict):
        return sizes
    sizes["tail_guard"] = _json_bytes(tail_guard)
    for key in ["near", "far"]:
        block = tail_guard.get(key)
        if isinstance(block, dict):
            sizes[f"tail_guard.{key}"] = _json_bytes(block)
            tf_states = block.get("tf_states")
            if isinstance(tf_states, dict):
                sizes[f"tail_guard.{key}.tf_states"] = _json_bytes(tf_states)
            marks = block.get("marks")
            if isinstance(marks, dict):
                sizes[f"tail_guard.{key}.marks"] = _json_bytes(marks)
    return sizes


def _ohlcv_final_duplicate(payload: Dict[str, Any]) -> Optional[bool]:
    final_1m = payload.get("ohlcv_final_1m")
    final_map = payload.get("ohlcv_final")
    if not isinstance(final_map, dict) or "1m" not in final_map:
        return None
    final_map_1m = final_map.get("1m")
    if not isinstance(final_1m, dict) or not isinstance(final_map_1m, dict):
        return None
    return final_1m == final_map_1m


def _sample_report(path: Path) -> Optional[SampleReport]:
    payload = _load_json(path)
    if payload is None:
        return None
    bytes_utf8 = _json_bytes(payload)
    section_bytes: Dict[str, int] = {}
    for key, value in payload.items():
        section_bytes[str(key)] = _json_bytes({key: value})
    top_sections = sorted(section_bytes.items(), key=lambda kv: kv[1], reverse=True)[:5]
    errors_count, errors_by_code, errors_duplicates = _errors_stats(payload.get("errors"))
    tail_guard_sizes = _tail_guard_sizes(payload.get("tail_guard"))
    return SampleReport(
        path=str(path),
        bytes_utf8=bytes_utf8,
        top_level_keys=len(payload.keys()),
        section_bytes=section_bytes,
        top_sections=top_sections,
        errors_count=errors_count,
        errors_by_code=errors_by_code,
        errors_duplicates=errors_duplicates,
        tail_guard_sizes=tail_guard_sizes,
        ohlcv_final_duplicate=_ohlcv_final_duplicate(payload),
    )


def _gather_paths(target: Path) -> List[Path]:
    if target.is_file():
        return [target]
    if not target.exists():
        return []
    paths = [p for p in target.glob("*.json") if p.is_file()]
    paths = [p for p in paths if p.name not in {"size_report.json"}]
    return sorted(paths)


def main() -> int:
    if len(sys.argv) < 2:
        print("Очікується шлях до файлу або папки з JSON (data/audit_status_bloat)")
        return 2
    target = Path(sys.argv[1])
    paths = _gather_paths(target)
    if not paths:
        print("Не знайдено JSON файлів для аналізу")
        return 1
    reports: List[SampleReport] = []
    for path in paths:
        report = _sample_report(path)
        if report is not None:
            reports.append(report)

    sizes = [r.bytes_utf8 for r in reports]
    summary = {
        "samples": len(reports),
        "min_bytes": min(sizes) if sizes else None,
        "median_bytes": _percentile(sizes, 50),
        "p90_bytes": _percentile(sizes, 90),
        "p99_bytes": _percentile(sizes, 99),
        "max_bytes": max(sizes) if sizes else None,
    }

    data_out = {
        "summary": summary,
        "reports": [
            {
                "path": r.path,
                "bytes_utf8": r.bytes_utf8,
                "top_level_keys": r.top_level_keys,
                "section_bytes": r.section_bytes,
                "top_sections": r.top_sections,
                "errors_count": r.errors_count,
                "errors_by_code": r.errors_by_code,
                "errors_duplicates": r.errors_duplicates,
                "tail_guard_sizes": r.tail_guard_sizes,
                "ohlcv_final_duplicate": r.ohlcv_final_duplicate,
            }
            for r in reports
        ],
    }

    out_dir = target if target.is_dir() else target.parent
    json_path = out_dir / "size_report.json"
    md_path = out_dir / "size_report.md"

    json_path.write_text(json.dumps(data_out, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: List[str] = []
    lines.append("# Status payload size report")
    lines.append("")
    lines.append(f"Samples: {summary['samples']}")
    lines.append(f"Min bytes: {summary['min_bytes']}")
    lines.append(f"Median bytes: {summary['median_bytes']}")
    lines.append(f"P90 bytes: {summary['p90_bytes']}")
    lines.append(f"P99 bytes: {summary['p99_bytes']}")
    lines.append(f"Max bytes: {summary['max_bytes']}")
    lines.append("")
    lines.append("## Per-sample top sections")
    for rep in reports:
        lines.append("")
        lines.append(f"### {Path(rep.path).name}")
        lines.append(f"bytes_utf8: {rep.bytes_utf8}; top_level_keys: {rep.top_level_keys}")
        lines.append("Top sections (bytes):")
        for key, size in rep.top_sections:
            lines.append(f"- {key}: {size}")
        lines.append(f"errors_count: {rep.errors_count}; errors_duplicates: {rep.errors_duplicates}")
        if rep.ohlcv_final_duplicate is not None:
            lines.append(f"ohlcv_final_1m == ohlcv_final['1m']: {rep.ohlcv_final_duplicate}")
        if rep.tail_guard_sizes:
            lines.append("tail_guard sizes:")
            for key, size in sorted(rep.tail_guard_sizes.items()):
                lines.append(f"- {key}: {size}")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"OK: {json_path}")
    print(f"OK: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
