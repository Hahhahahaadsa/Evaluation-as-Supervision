"""Build the SQLite index for fast review/business lookups (run once).

Scans the raw Yelp JSON files a single time and loads them into a SQLite
database with an index on ``business_id``. After this, ``loader.load_reviews``
goes from a ~1-minute full-file scan to a few-millisecond indexed query.

Usage (from the backend/ directory, with the venv active):

    python scripts/build_db.py
    python scripts/build_db.py --rebuild      # drop and rebuild if it exists

Output DB path defaults to backend/data/processed/yelp.db (override with the
YELP_DB_PATH env var). Once built, you may delete the raw .json files to reclaim
disk — the app reads everything from the DB.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

# Make `import app...` work when run as `python scripts/build_db.py`.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))

from app.data.loader import BUSINESS_PATH, DB_PATH, REVIEW_PATH  # noqa: E402

_BATCH = 50_000


def _build_businesses(conn: sqlite3.Connection) -> int:
    conn.execute("DROP TABLE IF EXISTS businesses")
    conn.execute(
        "CREATE TABLE businesses ("
        "  business_id TEXT PRIMARY KEY,"
        "  name TEXT,"
        "  address TEXT,"
        "  city TEXT,"
        "  state TEXT,"
        "  review_count INTEGER"
        ")"
    )

    def rows():
        with open(BUSINESS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                b = json.loads(line)
                yield (
                    b["business_id"],
                    b["name"],
                    b.get("address", ""),
                    b.get("city", ""),
                    b.get("state", ""),
                    b.get("review_count", 0),
                )

    count = 0
    batch = []
    for row in rows():
        batch.append(row)
        if len(batch) >= _BATCH:
            conn.executemany("INSERT OR REPLACE INTO businesses VALUES (?,?,?,?,?,?)", batch)
            count += len(batch)
            batch.clear()
    if batch:
        conn.executemany("INSERT OR REPLACE INTO businesses VALUES (?,?,?,?,?,?)", batch)
        count += len(batch)
    return count


def _build_reviews(conn: sqlite3.Connection) -> int:
    conn.execute("DROP TABLE IF EXISTS reviews")
    conn.execute(
        "CREATE TABLE reviews ("
        "  review_id TEXT,"
        "  business_id TEXT,"
        "  stars INTEGER,"
        "  text TEXT,"
        "  date TEXT"
        ")"
    )

    count = 0
    batch = []
    last_report = time.perf_counter()
    with open(REVIEW_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            batch.append((
                r["review_id"],
                r["business_id"],
                int(r["stars"]),
                r["text"],
                r["date"],
            ))
            if len(batch) >= _BATCH:
                conn.executemany("INSERT INTO reviews VALUES (?,?,?,?,?)", batch)
                count += len(batch)
                batch.clear()
                if time.perf_counter() - last_report > 5:
                    print(f"  ...{count:,} reviews inserted")
                    last_report = time.perf_counter()
    if batch:
        conn.executemany("INSERT INTO reviews VALUES (?,?,?,?,?)", batch)
        count += len(batch)

    print("  creating index on business_id...")
    conn.execute("CREATE INDEX idx_reviews_business ON reviews(business_id)")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the SQLite review/business index.")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild even if the DB exists.")
    args = parser.parse_args()

    if os.path.exists(DB_PATH) and not args.rebuild:
        print(f"DB already exists at {DB_PATH}. Use --rebuild to overwrite.")
        return 0

    for path, label in ((BUSINESS_PATH, "business"), (REVIEW_PATH, "review")):
        if not os.path.exists(path):
            print(f"Missing {label} dataset: {path}")
            return 1

    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    if args.rebuild and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    t0 = time.perf_counter()
    conn = sqlite3.connect(DB_PATH)
    try:
        # Speed up bulk load — safe because we can just rebuild on failure.
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")

        print("Building businesses table...")
        n_biz = _build_businesses(conn)
        conn.commit()
        print(f"  {n_biz:,} businesses.")

        print("Building reviews table (this scans the 5GB file once)...")
        n_rev = _build_reviews(conn)
        conn.commit()
        print(f"  {n_rev:,} reviews.")
    finally:
        conn.close()

    size_gb = os.path.getsize(DB_PATH) / 1e9
    print(f"\nDone in {time.perf_counter() - t0:.0f}s -> {DB_PATH} ({size_gb:.1f} GB)")
    print("load_reviews now uses the index automatically. You may delete the raw .json files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
