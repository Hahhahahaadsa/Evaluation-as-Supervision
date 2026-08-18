# Mock inputs and expected outputs for offline testing of Analysis and Reasoning agents.

# ── Analysis Agent ────────────────────────────────────────────────────────────

MOCK_REVIEW = {
    "review_id": "abc123",
    "stars": 2,
    "text": (
        "The food was cold and tasteless. Our waiter was rude and ignored us for 20 minutes. "
        "Waited 45 minutes just to get a table. Prices are way too high for what you get."
    ),
    "date": "2024-03-15",
}

MOCK_REVIEW_POSITIVE = {
    "review_id": "xyz789",
    "stars": 5,
    "text": "Amazing food and very friendly staff. The ambience was cozy and prices were reasonable.",
    "date": "2024-04-01",
}

MOCK_ANALYSIS_OUTPUT = {
    "review_id": "abc123",
    "sentiment": "negative",
    "aspects": [
        {"category": "food_quality", "label": "negative"},
        {"category": "staff_attitude", "label": "negative"},
        {"category": "wait_time", "label": "negative"},
        {"category": "pricing", "label": "negative"},
    ],
    "status": "success",
    "error_detail": None,
}

MOCK_ANALYSIS_OUTPUT_POSITIVE = {
    "review_id": "xyz789",
    "sentiment": "positive",
    "aspects": [
        {"category": "food_quality", "label": "positive"},
        {"category": "staff_attitude", "label": "positive"},
        {"category": "ambience", "label": "positive"},
        {"category": "pricing", "label": "positive"},
    ],
    "status": "success",
    "error_detail": None,
}

# ── Reasoning Agent ───────────────────────────────────────────────────────────

MOCK_REASONING_INPUT = {
    "business_id": "biz456",
    "sample_size": 3,
    "analysis_results": [
        {
            "review_id": "abc123",
            "sentiment": "negative",
            "aspects": [
                {"category": "food_quality", "label": "negative"},
                {"category": "staff_attitude", "label": "negative"},
                {"category": "wait_time", "label": "negative"},
            ],
        },
        {
            "review_id": "def456",
            "sentiment": "mixed",
            "aspects": [
                {"category": "food_quality", "label": "positive"},
                {"category": "staff_attitude", "label": "negative"},
                {"category": "wait_time", "label": "negative"},
            ],
        },
        {
            "review_id": "ghi789",
            "sentiment": "negative",
            "aspects": [
                {"category": "wait_time", "label": "negative"},
                {"category": "cleanliness", "label": "negative"},
            ],
        },
    ],
}

MOCK_REASONING_OUTPUT = {
    "patterns": [
        {
            "description": "Long wait times reported consistently across reviews",
            "aspect": "wait_time",
            "frequency": 1.0,
            "evidence_review_ids": ["abc123", "def456", "ghi789"],
        },
        {
            "description": "Staff attitude issues recurring across multiple reviews",
            "aspect": "staff_attitude",
            "frequency": 0.67,
            "evidence_review_ids": ["abc123", "def456"],
        },
    ],
    "root_causes": [
        {
            "pattern": "Long wait times reported consistently across reviews",
            "cause": "Understaffing during peak hours",
            "confidence": "high",
        },
        {
            "pattern": "Staff attitude issues recurring across multiple reviews",
            "cause": "Insufficient customer service training",
            "confidence": "medium",
        },
    ],
    "status": "success",
    "error_detail": None,
}

# ── Invalid output (for retry/self-correction tests) ─────────────────────────

MOCK_INVALID_LLM_OUTPUT = {
    "wrong_field": "this does not match any schema",
}

MOCK_REASONING_OUTPUT_FREQUENCY_OUT_OF_RANGE = {
    "patterns": [
        {
            "description": "Long wait times reported consistently",
            "aspect": "wait_time",
            "frequency": 1.5,
            "evidence_review_ids": ["abc123"],
        }
    ],
    "root_causes": [],
    "status": "success",
    "error_detail": None,
}

MOCK_REASONING_OUTPUT_EMPTY_EVIDENCE = {
    "patterns": [
        {
            "description": "Long wait times reported consistently",
            "aspect": "wait_time",
            "frequency": 0.8,
            "evidence_review_ids": [],
        }
    ],
    "root_causes": [],
    "status": "success",
    "error_detail": None,
}
