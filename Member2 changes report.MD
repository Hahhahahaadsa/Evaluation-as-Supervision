# Member 2 — Data Pipeline: Changes & Design Decisions

**Author:** Khánh (Member 2)  
**Component:** Data Pipeline (`loader.py`, `matching.py`, `preprocessor.py`)  
**Date:** June 2026

> **Historical component report, reviewed 2026-07-14.** The implementation now
> supports an optional SQLite index, seeded random raw/SQLite sampling, and a
> validated request-level cap. Current project findings are in
> [`PROJECT_AUDIT.md`](PROJECT_AUDIT.md).

---

## 1. Overview

The original project brief specified a data pipeline responsible for loading the Yelp dataset, performing fuzzy business name matching, and producing a cleaned Pandas DataFrame for downstream agents. This document outlines the implementation decisions made and deviations from the original specification.

---

## 2. Changes from Original Specification

### 2.1 Fuzzy Matching Logic — Extended Result Set for Exact Matches

**Original spec:**  
> "Fuzzy matching with top-3 candidates returned for user confirmation."

**Implementation:**  
The system returns a variable number of results depending on match score:
- If the highest score is **100 (exact match)**: score-100 businesses from the
  matcher candidate result are returned, sorted by `review_count` descending.
- If the highest score is **below 100**: top 3 candidates are returned, sorted by score then `review_count`.

**Reason:**  
A restaurant chain such as McDonald's may have dozens of branches in the dataset,
all sharing the same name and therefore all scoring 100. Exact matches are not
limited by `top_n`, but RapidFuzz extraction currently has `limit=50`; this is
not literally every matching branch.

---

### 2.2 Fuzzy Matching Library — Replaced `fuzzywuzzy` with `rapidfuzz`

**Original spec:**  
`fuzzywuzzy` was listed as the matching library.

**Implementation:**  
`rapidfuzz` is used instead of `fuzzywuzzy`.

**Reason:**  
The Yelp business dataset contains approximately 150,000 records. Running `fuzzywuzzy` against the full dataset produced unacceptable load times (~10–15 seconds per query). `rapidfuzz` implements the same Levenshtein-based algorithm in C/C++, producing identical match scores while reducing query time to under 1 second. No accuracy trade-off is involved.

---

### 2.3 Pre-filtering Before Fuzzy Match

**Original spec:**  
No pre-filtering was specified.

**Implementation:**  
Before fuzzy matching, the business list is pre-filtered to only include businesses whose name starts with the same first character as the query (case-insensitive). If fewer than 10 candidates remain after filtering, the full list is used as a fallback.

**Reason:**  
Reduces the fuzzy match candidate pool from ~150,000 to ~5,000–10,000 records, significantly improving response time while maintaining accuracy for standard queries.

---

### 2.4 In-memory Caching of Business Dataset

**Original spec:**  
No caching was specified.

**Implementation:**  
The business dataset is loaded from `business.json` once and stored in a module-level `_businesses_cache` list. Subsequent calls to `search_business()` read from the cache rather than re-reading the file.

**Reason:**  
When deployed as a FastAPI server, multiple users may submit search queries concurrently. Without caching, each query would re-read the full ~150k-record file from disk. The cache ensures the file is read once at server startup and all subsequent queries are served from memory.

---

### 2.5 Additional Business Metadata — `review_count`

**Original spec:**  
The business record was specified to include: `business_id`, `name`, `city`, `state`.

**Implementation:**  
`review_count` was added to the business record.

**Reason:**  
Used as a tiebreaker when multiple branches share the same fuzzy score. Branches with more reviews are ranked higher, as they provide more data for downstream LLM analysis.

`address` was also added to help users distinguish between branches of the same chain.

---

### 2.6 Dual Output Files

**Original spec:**  
A single preprocessed DataFrame as output.

**Implementation:**  
Two JSON files are saved to `backend/data/processed/`:
- `sample_reviews.json` — full 5-column DataFrame (review_id, business_id, stars, text, date)
- `sample_reviews_text.json` — text-only file containing only the `text` field

**Reason:**  
The full file is consumed by the Orchestrator and downstream agents that require all metadata. The text-only file is provided as a lightweight input for LLM processing, reducing token overhead when agents only need review content.

---

### 2.7 Review Count Cap

**Original spec:**  
> "The system caps analysis at the most recent 500 reviews per business by default."

**Implementation:**  
The cap is set to **100 reviews** via the `MAX_REVIEW_SAMPLE` environment variable in `.env`.

**Reason:**  
During development and testing, 100 reviews provides sufficient data for the
Analysis Agent while bounding LLM cost. The current cap is configured through
`MAX_REVIEW_SAMPLE`, but the binding project decision keeps the maximum at 100.
The loader sorts candidates by review ID and samples with `RANDOM_SEED`, making
selection reproducible across raw JSON and SQLite for the same inputs.

---

## 3. Architecture — File Responsibilities

| File | Responsibility |
|---|---|
| `app/data/matching.py` | Fuzzy search logic, pre-filtering, deduplication, sorting |
| `app/data/loader.py` | File I/O, business cache, review extraction |
| `app/data/preprocessor.py` | DataFrame cleaning, schema validation, type enforcement |
| `tests/test_data_pipeline.py` | Mocked interactive data-flow test and file output |
| `scripts/build_db.py` | One-time raw JSON to SQLite index builder |

---

## 4. Interface Contract — Output Schema

The preprocessed DataFrame passed to the Orchestrator Agent adheres to the following contract:

| Column | Type | Description |
|---|---|---|
| `review_id` | string | Unique review identifier |
| `business_id` | string | Yelp business identifier |
| `stars` | int64 (1–5) | Star rating, clipped to valid range |
| `text` | string | Review comment, stripped of whitespace |
| `date` | datetime64 | Review date, parsed from string |

This schema is frozen. Any changes require team agreement as downstream agents (Member 3, Member 4) depend on it.

---

## 5. Environment Variables

| Variable | Default | Description |
|---|---|---|
| `YELP_BUSINESS_PATH` | `backend/data/raw/yelp_academic_dataset_business.json` | Path to business dataset |
| `YELP_REVIEW_PATH` | `backend/data/raw/yelp_academic_dataset_review.json` | Path to review dataset |
| `YELP_DB_PATH` | `backend/data/processed/yelp.db` | Optional SQLite index |
| `MAX_REVIEW_SAMPLE` | `100` | Maximum reviews to extract per business |
| `RANDOM_SEED` | `42` | Seed for reproducible random review selection |


## 6. Setup after pulling

### 6.1 Build the SQLite index (one-time, after pulling)

The raw `.json` files and the generated SQLite database are **git-ignored** (too
large for git), so each teammate builds the index locally from their own copy of
the dataset.

1. Place the Yelp files in `backend/data/raw/`:
   - `yelp_academic_dataset_business.json`
   - `yelp_academic_dataset_review.json`
2. From `backend/`, run the one-time build (~2–3 minutes; scans the 5 GB review
   file once):

   ```bash
   python scripts/build_db.py            # add --rebuild to overwrite an existing DB
   ```

   This creates `backend/data/processed/yelp.db` with a `reviews` and
   `businesses` table indexed by `business_id`.

After this, `loader.load_reviews` queries the index (a few **milliseconds**)
instead of scanning the raw file. The 2026-07-14 audit measured **77.48 seconds**
without the index. Once built, you may delete the
raw `.json` files to reclaim disk — the app reads everything from the DB.

> Fallback: if `yelp.db` is missing but the raw `.json` files are present, the app
> still works by scanning the files directly (just slower). If neither is present,
> there is no data to analyse. Override the DB location with `YELP_DB_PATH`.

Known build limitation: the DB is written directly to its final path. An
interrupted build can leave a partial file that the loader treats as available.
