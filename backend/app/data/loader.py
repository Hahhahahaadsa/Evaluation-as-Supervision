import os
import json
import sqlite3
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from app.data.matching import fuzzy_search

load_dotenv()

# Resolve dataset paths against the repository root so they work no matter the
# current working directory (project root, backend/, or anywhere else).
# loader.py lives at <repo>/backend/app/data/loader.py -> parents[3] == <repo>.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve(path_str: str) -> str:
    path = Path(path_str)
    return str(path if path.is_absolute() else _REPO_ROOT / path)


BUSINESS_PATH = _resolve(
    os.getenv("YELP_BUSINESS_PATH", "backend/data/raw/yelp_academic_dataset_business.json")
)
REVIEW_PATH = _resolve(
    os.getenv("YELP_REVIEW_PATH", "backend/data/raw/yelp_academic_dataset_review.json")
)
# The default stays 100 — that is the interactive demo's per-business budget and
# nothing about the app changes. The *ceiling* is higher so the supervision
# study can raise it: its top stratum sits at 214 reviews, and capping there
# would collapse the p75 and p90 strata into the same analysed sample size,
# leaving Figure 2 with nothing to show at the top of the distribution.
# Raising this costs tokens linearly — see scripts/run_study.py.
MAX_REVIEW_HARD_CEILING = 500
MAX_REVIEWS = int(os.getenv("MAX_REVIEW_SAMPLE", 100))
RANDOM_SEED = int(os.getenv("RANDOM_SEED", 42))
if not 1 <= MAX_REVIEWS <= MAX_REVIEW_HARD_CEILING:
    raise ValueError(
        f"MAX_REVIEW_SAMPLE must be between 1 and {MAX_REVIEW_HARD_CEILING}"
    )

# SQLite index built by backend/scripts/build_db.py. When present, business/review
# lookups query the indexed DB (milliseconds) instead of scanning the raw JSON
# files (~1 minute). When absent, everything falls back to the raw-file path.
DB_PATH = _resolve(os.getenv("YELP_DB_PATH", "backend/data/processed/yelp.db"))

# Cache — load once only
_businesses_cache = []


def _db_available() -> bool:
    return bool(DB_PATH) and os.path.exists(DB_PATH)


def _load_businesses() -> list[dict]:
    global _businesses_cache
    if _businesses_cache:
        return _businesses_cache

    if _db_available():
        print("Loading business dataset from SQLite...")
        conn = sqlite3.connect(DB_PATH)
        try:
            cur = conn.execute(
                "SELECT business_id, name, address, city, state, review_count FROM businesses"
            )
            for bid, name, address, city, state, review_count in cur:
                _businesses_cache.append({
                    "business_id":  bid,
                    "name":         name,
                    "address":      address or "",
                    "city":         city or "",
                    "state":        state or "",
                    "review_count": review_count or 0,
                })
        finally:
            conn.close()
        print(f"Loaded {len(_businesses_cache)} businesses.")
        return _businesses_cache

    print("Loading business dataset...")
    with open(BUSINESS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            b = json.loads(line)
            _businesses_cache.append({
                "business_id":  b["business_id"],
                "name":         b["name"],
                "address":      b.get("address", ""),
                "city":         b.get("city", ""),
                "state":        b.get("state", ""),
                "review_count": b.get("review_count", 0),
            })
    print(f"Loaded {len(_businesses_cache)} businesses.")
    return _businesses_cache


def get_business(business_id: str) -> dict | None:
    """Look up a single business by its exact id, bypassing fuzzy name search.

    Returns the same shape as search_business() entries (minus ``score``), or
    None when the id is not present. Used by --business-id and by the batch
    study runner, where a name lookup would be ambiguous and non-reproducible.
    """
    for b in _load_businesses():
        if b.get("business_id") == business_id:
            return dict(b)
    return None


def search_business(name: str, top_n: int = 3) -> list[dict]:
    """Load businesses from cache and fuzzy match against the entered name."""
    businesses = _load_businesses()
    return fuzzy_search(name, businesses, top_n)


_REVIEW_COLUMNS = ["review_id", "business_id", "stars", "text", "date"]


def _sample_reviews(df: pd.DataFrame, sample_size: int | None = None) -> pd.DataFrame:
    """Return a reproducible random sample independent of input row order."""
    limit = MAX_REVIEWS if sample_size is None else sample_size
    if not 1 <= limit <= MAX_REVIEWS:
        raise ValueError(f"sample_size must be between 1 and {MAX_REVIEWS}")
    candidates = df.sort_values("review_id")
    if len(df) <= limit:
        return candidates.reset_index(drop=True)
    return (
        candidates.sample(n=limit, random_state=RANDOM_SEED)
        .reset_index(drop=True)
    )


def _load_reviews_from_db(business_id: str, sample_size: int | None = None) -> pd.DataFrame:
    """Fetch and reproducibly sample reviews for a business from the index."""
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT review_id, business_id, stars, text, date "
            "FROM reviews WHERE business_id = ?",
            (business_id,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print(f"No reviews found for business_id: {business_id}")
        return pd.DataFrame(columns=_REVIEW_COLUMNS)

    df = pd.DataFrame(rows, columns=_REVIEW_COLUMNS)
    df["date"] = pd.to_datetime(df["date"])
    sampled = _sample_reviews(df, sample_size)
    print(f"Business has {len(df)} reviews — randomly selected {len(sampled)}.")
    return sampled


def load_reviews(business_id: str, sample_size: int | None = None) -> pd.DataFrame:
    """Load a seeded random review sample for a business."""
    if _db_available():
        return _load_reviews_from_db(business_id, sample_size)

    rows = []
    with open(REVIEW_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("business_id") != business_id:
                continue
            rows.append({
                "review_id":   r["review_id"],
                "business_id": r["business_id"],
                "stars":       int(r["stars"]),
                "text":        r["text"],
                "date":        r["date"],
            })

    if not rows:
        print(f"No reviews found for business_id: {business_id}")
        return pd.DataFrame(columns=["review_id", "business_id", "stars", "text", "date"])

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    sampled = _sample_reviews(df, sample_size)
    print(f"Business has {len(df)} reviews — randomly selected {len(sampled)}.")
    return sampled
