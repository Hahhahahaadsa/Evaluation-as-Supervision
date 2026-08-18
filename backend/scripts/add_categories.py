"""Backfill the ``categories`` column on the businesses table (one-off).

WHY THIS EXISTS: scripts/build_db.py ingests every business in the Yelp dump
and does not keep the ``categories`` field, so yelp.db contains all 150,346
businesses across every category -- hotels, car dealers, visitor centres. That
is fine for the interactive demo, where the user names the restaurant they
want, but it is NOT fine for the stratified study sampler, which would
otherwise draw non-restaurants into a sample the paper describes as restaurant
reviews. The seven-aspect taxonomy (food_quality, wait_time, ambience, ...) is
restaurant-specific, so a car dealership would generate aspect-misalignment and
untraceable-recommendation detections that are artefacts of domain mismatch
rather than genuine grounding defects -- inflating the paper's headline number.

This reads only the business JSON (~119 MB), not the 5.3 GB review file, so it
takes seconds and does not require rebuilding the database.

Usage (from backend/, venv active):
    python scripts/add_categories.py
"""

import json
import sqlite3
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.data.loader import BUSINESS_PATH, DB_PATH  # noqa: E402

_BATCH = 50_000


def main() -> int:
    if not Path(DB_PATH).exists():
        print(f"Database not found: {DB_PATH}")
        return 1
    if not Path(BUSINESS_PATH).exists():
        print(f"Business JSON not found: {BUSINESS_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(businesses)")}
        if "categories" not in cols:
            print("Adding categories column ...")
            conn.execute("ALTER TABLE businesses ADD COLUMN categories TEXT")
            conn.commit()
        else:
            print("categories column already present -- refreshing values.")

        print(f"Streaming {BUSINESS_PATH} ...")
        batch, total = [], 0
        with open(BUSINESS_PATH, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    b = json.loads(line)
                except json.JSONDecodeError:
                    continue
                bid = b.get("business_id")
                if not bid:
                    continue
                batch.append((b.get("categories") or "", bid))
                if len(batch) >= _BATCH:
                    conn.executemany(
                        "UPDATE businesses SET categories = ? WHERE business_id = ?", batch
                    )
                    conn.commit()
                    total += len(batch)
                    batch = []
                    print(f"  {total:,} updated ...", flush=True)
        if batch:
            conn.executemany(
                "UPDATE businesses SET categories = ? WHERE business_id = ?", batch
            )
            conn.commit()
            total += len(batch)

        n_rest = conn.execute(
            "SELECT COUNT(*) FROM businesses WHERE categories LIKE '%Restaurants%'"
        ).fetchone()[0]
        n_all = conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
        print(f"\n{total:,} businesses updated.")
        print(f"{n_rest:,} of {n_all:,} carry the 'Restaurants' category.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
