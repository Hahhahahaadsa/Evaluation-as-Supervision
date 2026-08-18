"""Stratified business sampler for the supervision study (build item 3).

Draws businesses from yelp.db at percentile bands of *actual* review count, so
the workload sample spans the real distribution instead of over-representing
the high-count tail that uniform sampling would favour (FINDINGS F1 / Insight
I7: p10=6, p25=8, p50=15, p75=38, p90=101 across 150,346 businesses).

Two deliberate choices:

* Counts come from the ``reviews`` table, not ``businesses.review_count``.
  The latter is Yelp's own reported total for the business; the former is what
  this database actually holds and therefore what the pipeline can actually
  analyse. Reporting a stratum by a number we cannot load would be dishonest.
* Selection within a stratum is the ``--per-stratum`` businesses whose review
  count is nearest the target percentile, with ties broken by a seeded shuffle,
  so the sample is reproducible from (db, seed, percentiles, per_stratum).

Usage (from backend/, venv active):
    python scripts/sample_businesses.py --out out_study/sample.json
    python scripts/sample_businesses.py --per-stratum 5 --seed 20260803

The output JSON is the input to scripts/run_study.py.
"""

import argparse
import json
import os
import random
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The repository path contains non-ASCII characters and the Windows console
# defaults to cp1252, which cannot encode them. Force UTF-8 on our streams so a
# two-hour batch cannot die on a print().
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


from app.core import supervision  # noqa: E402
from app.data import loader  # noqa: E402

DEFAULT_PERCENTILES = [25, 50, 75, 90]


def _percentile(sorted_vals: list[int], pct: float) -> int:
    """Nearest-rank percentile — no interpolation, so the value is a real count."""
    if not sorted_vals:
        raise ValueError("no businesses to take percentiles of")
    k = max(1, int(round(pct / 100.0 * len(sorted_vals))))
    return sorted_vals[min(k, len(sorted_vals)) - 1]


def _has_category(raw: str, wanted: str) -> bool:
    """Exact token match against Yelp's comma-separated category string.

    Token match, not substring: ``LIKE '%Restaurants%'`` would also admit
    categories such as "Pop-Up Restaurants" (fine) but the token test keeps the
    rule explicit and auditable, which matters because this filter decides what
    the paper's headline number is computed over.
    """
    return wanted.lower() in {c.strip().lower() for c in (raw or "").split(",")}


def load_counts(db_path: str, min_reviews: int, category: str | None) -> list[dict]:
    """Every business with at least ``min_reviews`` rows in the reviews table.

    Counts come from the reviews table, so they reflect what this database can
    actually serve. When ``category`` is given, only businesses carrying that
    Yelp category are returned -- without it the pool is every business in the
    dump (hotels, car dealers, visitor centres), which the restaurant-specific
    aspect taxonomy would mis-analyse.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(businesses)")}
        if category and "categories" not in cols:
            raise SystemExit(
                "businesses.categories is missing -- run scripts/add_categories.py "
                "first, or pass --category '' to sample across all categories."
            )
        rows = conn.execute(
            """
            SELECT r.business_id, COALESCE(b.name, ''), COUNT(*) AS n,
                   COALESCE(b.categories, '')
            FROM reviews r
            LEFT JOIN businesses b ON b.business_id = r.business_id
            GROUP BY r.business_id
            HAVING n >= ?
            ORDER BY n ASC, r.business_id ASC
            """,
            (min_reviews,),
        ).fetchall()
    finally:
        conn.close()

    pool = []
    for bid, name, n, cats in rows:
        if category and not _has_category(cats, category):
            continue
        pool.append({"business_id": bid, "name": name, "review_count": n})
    return pool


def stratify(pool: list[dict], percentiles: list[int], per_stratum: int, seed: int,
              category: str | None = None) -> dict:
    counts = sorted(b["review_count"] for b in pool)
    rng = random.Random(seed)

    shuffled = list(pool)
    rng.shuffle(shuffled)  # seeded tie-break, applied before the stable sort below

    taken: set[str] = set()
    strata = []
    for pct in percentiles:
        target = _percentile(counts, pct)
        # Nearest by |count - target|; the prior shuffle makes ties deterministic
        # given the seed but not biased toward any particular id ordering.
        ranked = sorted(
            (b for b in shuffled if b["business_id"] not in taken),
            key=lambda b: abs(b["review_count"] - target),
        )
        picked = ranked[:per_stratum]
        for b in picked:
            taken.add(b["business_id"])
        picked.sort(key=lambda b: b["review_count"])
        strata.append({
            "stratum": f"p{pct}",
            "target_percentile": pct,
            "target_review_count": target,
            "n_businesses": len(picked),
            "review_count_min": picked[0]["review_count"] if picked else None,
            "review_count_median": picked[len(picked) // 2]["review_count"] if picked else None,
            "review_count_max": picked[-1]["review_count"] if picked else None,
            "businesses": picked,
        })

    return {
        "meta": {
            "db_path": loader.DB_PATH,
            "seed": seed,
            "category_filter": category or None,
            "per_stratum": per_stratum,
            "percentiles": percentiles,
            "pool_size": len(pool),
            "min_reviews_floor": min(counts) if counts else None,
            "max_reviews_loaded_per_business": loader.MAX_REVIEWS,
            "min_viable_n": supervision.MIN_VIABLE_N,
            "low_confidence_n": supervision.LOW_CONFIDENCE_N,
            "pool_percentiles": {f"p{p}": _percentile(counts, p) for p in (10, 25, 50, 75, 90)},
        },
        "strata": strata,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=loader.DB_PATH, help="Path to yelp.db.")
    ap.add_argument("--out", default="out_study/sample.json", help="Where to write the sample.")
    ap.add_argument("--per-stratum", type=int, default=5, help="Businesses per stratum (default 5).")
    ap.add_argument("--seed", type=int, default=20260803, help="Tie-break seed.")
    ap.add_argument(
        "--category",
        default="Restaurants",
        help=(
            "Yelp category every sampled business must carry (default "
            "'Restaurants'). Pass an empty string to sample across all "
            "categories -- see the note in load_counts() before doing so."
        ),
    )
    ap.add_argument(
        "--percentiles",
        default=",".join(str(p) for p in DEFAULT_PERCENTILES),
        help="Comma-separated target percentiles (default 25,50,75,90).",
    )
    ap.add_argument(
        "--min-reviews",
        type=int,
        default=supervision.MIN_VIABLE_N,
        help=(
            "Floor on loadable reviews. Defaults to MIN_VIABLE_N so the sample "
            "cannot contain a business the analysis stage would halt on."
        ),
    )
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"Database not found: {args.db}")
        return 1

    percentiles = [int(p) for p in args.percentiles.split(",") if p.strip()]

    print(f"Reading review counts from {args.db} ...")
    category = args.category.strip() or None
    pool = load_counts(args.db, args.min_reviews, category)
    if not pool:
        print("No businesses met the minimum review floor.")
        return 1
    print(f"  {len(pool)} businesses with >= {args.min_reviews} reviews"
          + (f" in category {category!r}" if category else " (ALL categories)"))

    sample = stratify(pool, percentiles, args.per_stratum, args.seed, category)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(sample, fh, indent=2, ensure_ascii=False)

    print(f"\nPool percentiles: {sample['meta']['pool_percentiles']}")
    print(f"\n{'stratum':<10}{'target':>8}{'n':>4}{'min':>6}{'med':>6}{'max':>6}")
    total = 0
    for s in sample["strata"]:
        total += s["n_businesses"]
        print(
            f"{s['stratum']:<10}{s['target_review_count']:>8}{s['n_businesses']:>4}"
            f"{s['review_count_min']:>6}{s['review_count_median']:>6}{s['review_count_max']:>6}"
        )
    print(f"\n{total} businesses written to {args.out}")
    if any(s["review_count_max"] and s["review_count_max"] > loader.MAX_REVIEWS for s in sample["strata"]):
        print(
            f"NOTE: some businesses hold more than MAX_REVIEWS={loader.MAX_REVIEWS} reviews; "
            "the pipeline will sample down to that cap. Report the loaded count, not this one."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
