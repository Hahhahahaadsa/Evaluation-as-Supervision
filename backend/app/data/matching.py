from rapidfuzz import process, fuzz


def fuzzy_search(name: str, businesses: list[dict], top_n: int = 3) -> list[dict]:
    """
    Fuzzy match tên business với pre-filtering.
    - Nếu score = 100: trả về tất cả có score 100, sort theo review_count
    - Nếu score < 100: trả về top_n, sort theo score rồi review_count
    """

    # Bước 1 — Pre-filter theo ký tự đầu tiên
    first_char = name[0].lower() if name else ""
    candidates = [
        b for b in businesses
        if b["name"] and b["name"][0].lower() == first_char
    ]

    # Fallback nếu pre-filter quá ít kết quả
    if len(candidates) < 10:
        candidates = businesses

    # Bước 2 — Fuzzy match trên tập nhỏ hơn
    names = [b["name"] for b in candidates]
    matches = process.extract(
        name,
        names,
        scorer=fuzz.ratio,
        limit=50
    )

    # Bước 3 — Deduplicate theo business_id
    seen = {}
    for match_name, score, idx in matches:
        biz = candidates[idx]
        bid = biz["business_id"]
        if bid not in seen:
            seen[bid] = {**biz, "score": score}

    # Bước 4 — Sort theo score rồi review_count
    all_results = sorted(
        seen.values(),
        key=lambda x: (x["score"], x["review_count"]),
        reverse=True
    )

    # Score = 100 → trả về tất cả
    if all_results and all_results[0]["score"] == 100:
        return [r for r in all_results if r["score"] == 100]

    # Score < 100 → trả về top_n
    return all_results[:top_n]