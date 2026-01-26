from __future__ import annotations

import io
import json
import os
import re
import sys
from typing import Any, Dict, List, cast

KEYWORDS = ["P3", "warmup", "backfill", "Exit Gate P3", "SSOT store"]


def _match_header(line: str) -> bool:
    if not line.startswith("## "):
        return False
    if "PRE" not in line and "POST" not in line:
        return False
    if not re.search(r"\d{4}-\d{2}-\d{2}", line):
        return False
    for keyword in KEYWORDS:
        if keyword in line:
            return True
    return False


def _ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path)


def scan_log_entries(lines: List[str]) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    total = len(lines)
    for idx, line in enumerate(lines):
        if not _match_header(line):
            continue
        line_no = idx + 1
        body_preview: List[str] = []
        j = idx + 1
        while j < total and not lines[j].startswith("## ") and len(body_preview) < 5:
            body_preview.append(lines[j].rstrip("\n"))
            j += 1
        matches.append(
            {
                "line": line_no,
                "header": line.rstrip("\n"),
                "body_preview": body_preview,
            }
        )
    return matches


def main() -> None:
    stdout = cast(Any, sys.stdout)
    if hasattr(stdout, "reconfigure"):
        stdout.reconfigure(encoding="utf-8")
    else:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    log_path = os.path.join(root, "Work", "01log.md")
    with open(log_path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()

    results = scan_log_entries(lines)

    for item in results:
        print(f"{item['header']}")
        print(f"line: {item['line']}")
        preview = cast(List[str], item.get("body_preview", []))
        for row in preview:
            print(f"{row}")
        print("")

    out_dir = os.path.join(root, "data", "audit_v3")
    _ensure_dir(out_dir)
    out_path = os.path.join(out_dir, "log_scan_report.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"entries": results}, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
