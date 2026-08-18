"""Data pipeline demo + automated test.

`run_demo()` contains the interactive end-to-end flow (search -> select ->
load -> preprocess -> save). Running this file directly (python -m / python
tests/test_data_pipeline.py) launches the interactive demo against the real Yelp
dataset. Under pytest, the demo is exercised non-interactively with mocked data,
so it never blocks on stdin or requires the dataset files.
"""

import json
import os
import sqlite3

import pandas as pd
import pytest
from pydantic import ValidationError

from app.data import loader, preprocessor
from app.main import ReportRequest


def run_demo(output_dir: str | None = None) -> pd.DataFrame | None:
    if output_dir is None:
        # <repo>/backend/tests/this_file -> parents[1] == <repo>/backend
        from pathlib import Path
        output_dir = str(Path(__file__).resolve().parents[1] / "data" / "processed")
    business_name = input("Restaurant name: ")
    results = loader.search_business(business_name)
    if not results:
        print("No matching business found.")
        return None

    if results[0]["score"] == 100:
        print(f"\n{len(results)} exact-match branch(es) found:\n")
    else:
        print(f"\nNo exact match. Top {len(results)} closest:\n")

    for i, r in enumerate(results):
        print(f"{i + 1}. {r['name']} — {r['address']}, {r['city']}, {r['state']} "
              f"(reviews={r['review_count']}, score={r['score']}, id={r['business_id']})")

    while True:
        try:
            choice = int(input(f"\nSelect branch (1-{len(results)}): "))
            if 1 <= choice <= len(results):
                break
            print(f"Please enter a number from 1 to {len(results)}.")
        except ValueError:
            print("Please enter a number.")

    selected = results[choice - 1]
    print(f"\n>> Selected: {selected['name']} - {selected['address']}, {selected['city']}\n")

    df_raw = loader.load_reviews(selected["business_id"])
    if df_raw.empty:
        print("No reviews found. Stopping.")
        return None

    df_clean = preprocessor.preprocess(df_raw)
    print(f"Reviews after cleaning: {len(df_clean)}")

    os.makedirs(output_dir, exist_ok=True)
    full_path = os.path.join(output_dir, "sample_reviews.json")
    df_clean.to_json(full_path, orient="records", indent=2, force_ascii=False, date_format="iso")
    print(f"Saved: {full_path}")

    text_path = os.path.join(output_dir, "sample_reviews_text.json")
    df_clean[["text"]].to_json(text_path, orient="records", indent=2, force_ascii=False)
    print(f"Saved text-only: {text_path}")

    return df_clean


# --------------------------------------------------------------------------- #
# Automated test — mocks the pipeline so it runs without stdin or real data.
# --------------------------------------------------------------------------- #

def _fake_results() -> list[dict]:
    return [
        {
            "name": "Test Diner",
            "address": "1 Main St",
            "city": "Townsville",
            "state": "CA",
            "review_count": 120,
            "score": 100,
            "business_id": "b1",
        }
    ]


def _fake_reviews() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "review_id": ["r1", "r2", "r3"],
            "business_id": ["b1", "b1", "b1"],
            "stars": [5, 4, 3],
            "text": ["Great food", "Good service", "A bit slow"],
            "date": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]),
        }
    )
    return df


def test_run_demo_with_mocked_pipeline(monkeypatch, tmp_path):
    inputs = iter(["Test Diner", "1"])
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: next(inputs))
    monkeypatch.setattr(loader, "search_business", lambda name: _fake_results())
    monkeypatch.setattr(loader, "load_reviews", lambda business_id: _fake_reviews())
    monkeypatch.setattr(preprocessor, "preprocess", lambda df: df)

    df_clean = run_demo(output_dir=str(tmp_path))

    assert df_clean is not None
    assert len(df_clean) == 3
    assert (tmp_path / "sample_reviews.json").exists()
    assert (tmp_path / "sample_reviews_text.json").exists()


def test_run_demo_handles_no_matches(monkeypatch, tmp_path):
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "Unknown")
    monkeypatch.setattr(loader, "search_business", lambda name: [])

    assert run_demo(output_dir=str(tmp_path)) is None


def test_seeded_sampling_matches_raw_and_sqlite(monkeypatch, tmp_path):
    rows = [
        {
            "review_id": f"r{i}",
            "business_id": "b1",
            "stars": (i % 5) + 1,
            "text": f"review {i}",
            "date": f"2024-01-{i + 1:02d}",
        }
        for i in range(10)
    ]
    review_path = tmp_path / "reviews.json"
    review_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    monkeypatch.setattr(loader, "REVIEW_PATH", str(review_path))
    monkeypatch.setattr(loader, "DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setattr(loader, "MAX_REVIEWS", 5)
    monkeypatch.setattr(loader, "RANDOM_SEED", 42)

    raw_ids = loader.load_reviews("b1", sample_size=4)["review_id"].tolist()
    assert raw_ids == loader.load_reviews("b1", sample_size=4)["review_id"].tolist()
    assert set(raw_ids) != {"r6", "r7", "r8", "r9"}

    db_path = tmp_path / "reviews.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE reviews "
            "(review_id TEXT, business_id TEXT, stars INTEGER, text TEXT, date TEXT)"
        )
        conn.executemany(
            "INSERT INTO reviews VALUES (:review_id, :business_id, :stars, :text, :date)",
            reversed(rows),
        )
    monkeypatch.setattr(loader, "DB_PATH", str(db_path))

    assert loader.load_reviews("b1", sample_size=4)["review_id"].tolist() == raw_ids
    with pytest.raises(ValueError, match="between 1 and 5"):
        loader.load_reviews("b1", sample_size=0)


def test_report_request_validates_sample_size():
    assert ReportRequest(restaurant_name="Test", sample_size=100).sample_size == 100
    for invalid in (0, 101):
        with pytest.raises(ValidationError):
            ReportRequest(restaurant_name="Test", sample_size=invalid)


if __name__ == "__main__":
    run_demo()
