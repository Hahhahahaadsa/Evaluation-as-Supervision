# backend/tests/test_unit.py
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest
from app.data.preprocessor import preprocess
from app.data.matching import fuzzy_search


# ================================================
# Test preprocess() — không cần dataset thật
# ================================================

def make_df(rows):
    """Helper tạo DataFrame test nhanh."""
    df = pd.DataFrame(rows)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def test_preprocess_normal():
    """DataFrame bình thường — giữ nguyên."""
    df = make_df([
        {"review_id": "r1", "business_id": "b1", "stars": 4, "text": "Good food", "date": "2024-01-01"},
        {"review_id": "r2", "business_id": "b1", "stars": 2, "text": "Bad service", "date": "2024-01-02"},
    ])
    result = preprocess(df)
    assert len(result) == 2


def test_preprocess_drop_null_text():
    """Drop rows có text null."""
    df = make_df([
        {"review_id": "r1", "business_id": "b1", "stars": 4, "text": "Good food", "date": "2024-01-01"},
        {"review_id": "r2", "business_id": "b1", "stars": 2, "text": None, "date": "2024-01-02"},
    ])
    result = preprocess(df)
    assert len(result) == 1
    assert result.iloc[0]["review_id"] == "r1"


def test_preprocess_drop_null_review_id():
    """Drop rows có review_id null."""
    df = make_df([
        {"review_id": None, "business_id": "b1", "stars": 4, "text": "Good food", "date": "2024-01-01"},
        {"review_id": "r2", "business_id": "b1", "stars": 3, "text": "OK food",   "date": "2024-01-02"},
    ])
    result = preprocess(df)
    assert len(result) == 1
    assert result.iloc[0]["review_id"] == "r2"


def test_preprocess_drop_duplicates():
    """Drop duplicate review_id."""
    df = make_df([
        {"review_id": "r1", "business_id": "b1", "stars": 4, "text": "Good food", "date": "2024-01-01"},
        {"review_id": "r1", "business_id": "b1", "stars": 4, "text": "Good food", "date": "2024-01-01"},
    ])
    result = preprocess(df)
    assert len(result) == 1


def test_preprocess_clip_stars():
    """Stars ngoài range 1-5 phải được clip."""
    df = make_df([
        {"review_id": "r1", "business_id": "b1", "stars": 0, "text": "Bad", "date": "2024-01-01"},
        {"review_id": "r2", "business_id": "b1", "stars": 6, "text": "Good", "date": "2024-01-02"},
    ])
    result = preprocess(df)
    assert result.iloc[0]["stars"] == 1
    assert result.iloc[1]["stars"] == 5


def test_preprocess_strip_text():
    """Text có khoảng trắng thừa phải được strip."""
    df = make_df([
        {"review_id": "r1", "business_id": "b1", "stars": 4, "text": "  Good food  ", "date": "2024-01-01"},
    ])
    result = preprocess(df)
    assert result.iloc[0]["text"] == "Good food"


def test_preprocess_drop_empty_text_after_strip():
    """Text chỉ có khoảng trắng phải bị drop."""
    df = make_df([
        {"review_id": "r1", "business_id": "b1", "stars": 4, "text": "   ", "date": "2024-01-01"},
        {"review_id": "r2", "business_id": "b1", "stars": 3, "text": "OK",  "date": "2024-01-02"},
    ])
    result = preprocess(df)
    assert len(result) == 1


def test_preprocess_empty_dataframe():
    """DataFrame rỗng không crash."""
    df = pd.DataFrame(columns=["review_id", "business_id", "stars", "text", "date"])
    result = preprocess(df)
    assert result.empty


def test_preprocess_correct_schema():
    """Output đúng schema và kiểu dữ liệu."""
    df = make_df([
        {"review_id": "r1", "business_id": "b1", "stars": 4, "text": "Good", "date": "2024-01-01"},
    ])
    result = preprocess(df)
    assert list(result.columns) == ["review_id", "business_id", "stars", "text", "date"]
    assert result["stars"].dtype == "int64"
    assert str(result["date"].dtype).startswith("datetime")


# ================================================
# Test fuzzy_search() — không cần dataset thật
# ================================================

MOCK_BUSINESSES = [
    {"business_id": "b1", "name": "McDonald's", "address": "123 Main St", "city": "St. Louis",  "state": "MO", "review_count": 200},
    {"business_id": "b2", "name": "McDonald's", "address": "456 Oak Ave",  "city": "Las Vegas", "state": "NV", "review_count": 50},
    {"business_id": "b3", "name": "McDonald's", "address": "789 Elm Rd",   "city": "Phoenix",   "state": "AZ", "review_count": 100},
    {"business_id": "b4", "name": "Burger King", "address": "321 Pine St", "city": "Chicago",   "state": "IL", "review_count": 80},
]


def test_fuzzy_exact_match():
    """Tên chính xác → score = 100."""
    results = fuzzy_search("McDonald's", MOCK_BUSINESSES, top_n=3)
    assert results[0]["score"] == 100


def test_fuzzy_typo():
    """Tên viết sai vẫn tìm được."""
    results = fuzzy_search("Mcdonalds", MOCK_BUSINESSES, top_n=3)
    assert len(results) > 0
    assert results[0]["score"] >= 80


def test_fuzzy_no_duplicates():
    """Không có business_id trùng trong kết quả."""
    results = fuzzy_search("McDonald's", MOCK_BUSINESSES, top_n=3)
    ids = [r["business_id"] for r in results]
    assert len(ids) == len(set(ids))


def test_fuzzy_sort_by_review_count():
    """Khi score bằng nhau, sort theo review_count nhiều nhất."""
    results = fuzzy_search("McDonald's", MOCK_BUSINESSES, top_n=3)
    assert results[0]["review_count"] >= results[1]["review_count"]
    assert results[1]["review_count"] >= results[2]["review_count"]


def test_fuzzy_top_n():
    """top_n caps the result count for NON-exact matches.

    Exact (score==100) matches intentionally return all branches (see
    Member 2 changes report), so top_n is exercised with a typo query that
    scores below 100.
    """
    results = fuzzy_search("Mcdonald", MOCK_BUSINESSES, top_n=2)
    assert results[0]["score"] < 100
    assert len(results) == 2


def test_fuzzy_not_found():
    """Tên không tồn tại → score thấp."""
    results = fuzzy_search("xyzxyzxyz123", MOCK_BUSINESSES, top_n=3)
    assert results[0]["score"] < 60