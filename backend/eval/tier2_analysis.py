"""Tier 2 - labeled gold set for the analysis agent only.

The analysis agent is the only stage with objectively checkable answers.
Hand-label 30-50 reviews (see gold/analysis_gold.template.jsonl), run the
analysis agent on those review_ids, and compute:

    - sentiment accuracy
    - per-aspect macro-F1  (multi-label: one binary "is this aspect category
      mentioned at all" problem per AspectCategory, then macro-average)

Star rating is only a noisy cross-check (5 -> positive, 1-2 -> negative),
NOT ground truth.

Run:  python -m eval.tier2_analysis --gold eval/gold/analysis_gold.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

from sklearn.metrics import accuracy_score, f1_score

from app.agents.analysis_agent import analyse_reviews
from app.data import loader
from app.schemas.contracts import AspectCategory

GOLD_DEFAULT = "eval/gold/analysis_gold.jsonl"

ASPECT_CATEGORIES: tuple[str, ...] = tuple(AspectCategory.__args__)  # type: ignore[attr-defined]


def load_gold(path: str) -> list[dict]:
    """Read the gold JSONL: one {review_id, sentiment, aspects:[...]} per line.

    Lines carrying only a "_comment" key (see the template) are skipped.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"gold file not found: {path}. Copy eval/gold/analysis_gold.template.jsonl "
            "to analysis_gold.jsonl and hand-label 30-50 reviews first."
        )

    gold: list[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "_comment" in row:
                continue
            if "review_id" not in row or "sentiment" not in row:
                raise ValueError(f"{path}:{lineno}: gold row missing review_id/sentiment: {row}")
            row.setdefault("aspects", [])
            gold.append(row)

    if not gold:
        raise ValueError(f"{path} contains no labeled rows (only comments/blank lines)")
    return gold


def _fetch_reviews_by_id(review_ids: set[str]) -> dict[str, dict]:
    """Look up the review text/stars/date for a small set of review_ids.

    Prefers the SQLite index (fast); falls back to a single linear scan of the
    raw review file, stopping once every id has been found.
    """
    found: dict[str, dict] = {}

    if os.path.exists(loader.DB_PATH):
        conn = sqlite3.connect(loader.DB_PATH)
        try:
            placeholders = ",".join("?" for _ in review_ids)
            rows = conn.execute(
                f"SELECT review_id, business_id, stars, text, date FROM reviews "
                f"WHERE review_id IN ({placeholders})",
                tuple(review_ids),
            ).fetchall()
            for review_id, business_id, stars, text, date in rows:
                found[review_id] = {
                    "review_id": review_id,
                    "business_id": business_id,
                    "stars": stars,
                    "text": text,
                    "date": str(date),
                }
        finally:
            conn.close()
        return found

    remaining = set(review_ids)
    with open(loader.REVIEW_PATH, "r", encoding="utf-8") as fh:
        for line in fh:
            if not remaining:
                break
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rid = r.get("review_id")
            if rid in remaining:
                found[rid] = {
                    "review_id": rid,
                    "business_id": r.get("business_id"),
                    "stars": int(r["stars"]),
                    "text": r["text"],
                    "date": str(r.get("date", "")),
                }
                remaining.discard(rid)
    return found


def run_analysis_on_gold(gold: list[dict], batch_size: int = 10) -> list[dict]:
    """Fetch the gold review_ids' text and run the real analysis agent on them."""
    review_ids = {row["review_id"] for row in gold}
    reviews_by_id = _fetch_reviews_by_id(review_ids)

    missing = review_ids - reviews_by_id.keys()
    if missing:
        raise ValueError(f"{len(missing)} gold review_ids not found in the dataset: {sorted(missing)[:5]}...")

    ordered_reviews = [reviews_by_id[row["review_id"]] for row in gold]

    predictions: list[dict] = []
    for start in range(0, len(ordered_reviews), batch_size):
        batch = ordered_reviews[start : start + batch_size]
        predictions.extend(analyse_reviews(batch))
    return predictions


def score_sentiment(gold: list[dict], pred: list[dict]) -> float:
    """accuracy_score over the single-label sentiment field, aligned by review_id."""
    pred_by_id = {p.get("review_id"): p for p in pred}
    y_true, y_pred = [], []
    for row in gold:
        p = pred_by_id.get(row["review_id"])
        if p is None or p.get("status") != "success":
            continue
        y_true.append(row["sentiment"])
        y_pred.append(p.get("sentiment"))
    if not y_true:
        return 0.0
    return accuracy_score(y_true, y_pred)


def score_aspects_macro_f1(gold: list[dict], pred: list[dict]) -> dict[str, float]:
    """Per-aspect binary F1 (aspect mentioned vs not), macro-averaged.

    For each AspectCategory, builds a binary y_true/y_pred over the gold
    review_ids ("does this review mention this aspect at all, per the human
    label / the model's prediction") and scores with sklearn's binary F1.
    Categories with an undefined F1 (no positives in either y_true or y_pred)
    are excluded from the macro average and reported separately.
    """
    pred_by_id = {p.get("review_id"): p for p in pred}
    aligned_gold, aligned_pred = [], []
    for row in gold:
        p = pred_by_id.get(row["review_id"])
        if p is None or p.get("status") != "success":
            continue
        aligned_gold.append(row)
        aligned_pred.append(p)

    per_category: dict[str, float] = {}
    skipped: list[str] = []
    for category in ASPECT_CATEGORIES:
        y_true = [1 if any(a["category"] == category for a in row.get("aspects", [])) else 0 for row in aligned_gold]
        y_pred = [1 if any(a.get("category") == category for a in p.get("aspects", [])) else 0 for p in aligned_pred]

        if sum(y_true) == 0 and sum(y_pred) == 0:
            skipped.append(category)
            continue

        per_category[category] = f1_score(y_true, y_pred, zero_division=0)

    macro_f1 = sum(per_category.values()) / len(per_category) if per_category else 0.0
    return {"macro_f1": macro_f1, "per_category": per_category, "skipped_categories": skipped}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=GOLD_DEFAULT)
    args = ap.parse_args(argv[1:])

    try:
        gold = load_gold(args.gold)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}")
        return 1
    print(f"Loaded {len(gold)} gold-labeled reviews from {args.gold}")

    print("Fetching review text and running the analysis agent (real LLM calls)...")
    pred = run_analysis_on_gold(gold)

    sentiment_acc = score_sentiment(gold, pred)
    aspect_scores = score_aspects_macro_f1(gold, pred)

    print("\n=== Tier 2: analysis agent gold-set scores ===")
    print(f"Sentiment accuracy : {sentiment_acc:.3f}  (n={len(gold)})")
    print(f"Aspect macro-F1     : {aspect_scores['macro_f1']:.3f}")
    print("Per-aspect F1:")
    for category, f1 in aspect_scores["per_category"].items():
        print(f"  {category:<15}: {f1:.3f}")
    if aspect_scores["skipped_categories"]:
        print(f"  (no gold or predicted mentions, excluded from macro-avg: {aspect_scores['skipped_categories']})")

    out_path = os.path.join(os.path.dirname(args.gold) or ".", "tier2_scores.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(
            {"n_gold": len(gold), "sentiment_accuracy": sentiment_acc, **aspect_scores},
            fh,
            indent=2,
        )
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
