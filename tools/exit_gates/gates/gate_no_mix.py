from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Tuple

from config.config import load_config
from core.env_loader import load_env
from store.sqlite_store import SQLiteStore


def run() -> Tuple[bool, str]:
    return True, "SKIP: gate_no_mix запускається вручну через CLI"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--tfs", required=True)
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parents[3]
    load_env(root_dir)
    config = load_config()
    store = SQLiteStore(db_path=Path(config.store_path))
    store.init_schema(Path(__file__).resolve().parents[3] / "store" / "schema.sql")

    tfs = [tf.strip() for tf in args.tfs.split(",") if tf.strip()]
    conflicts = 0

    conn = store.connect()
    try:
        for tf in tfs:
            cur = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM bars_htf_final
                WHERE symbol = ? AND tf = ? AND complete = 1 AND source != 'history_agg'
                """,
                (args.symbol, tf),
            )
            conflicts += int(cur.fetchone()[0])
        cur = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM bars_1m_final
            WHERE symbol = ? AND complete = 1 AND source != 'history'
            """,
            (args.symbol,),
        )
        conflicts += int(cur.fetchone()[0])
    finally:
        conn.close()

    if conflicts == 0:
        print("OK: no_mix conflicts=0")
        return 0

    print(f"FAIL: no_mix conflicts={conflicts}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
