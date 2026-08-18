"""
Integration tests — make real LLM calls via the Gemini API.

Run with:
    cd backend
    python -m pytest tests/test_integration.py -v -m integration

Skip automatically when OPENAI_API_KEY is not set.
"""
import os

import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = pytest.mark.integration


def _api_key_missing():
    return not os.getenv("OPENAI_API_KEY")


skip_no_key = pytest.mark.skipif(_api_key_missing(), reason="OPENAI_API_KEY not set")

from tests.mock_data import (
    MOCK_REASONING_INPUT,
    MOCK_REVIEW,
    MOCK_REVIEW_POSITIVE,
)
from app.agents.analysis_agent import analyse_review
from app.agents.reasoning_agent import reason_over_reviews
from app.schemas.contracts import AnalysisOutput, ReasoningOutput


@skip_no_key
def test_analysis_agent_real_llm_negative_review():
    result = analyse_review(MOCK_REVIEW)

    assert result["status"] == "success", f"Agent returned error: {result.get('error_detail')}"
    assert result["review_id"] == MOCK_REVIEW["review_id"]
    assert result["sentiment"] in ("positive", "negative", "neutral", "mixed")
    assert isinstance(result["aspects"], list)
    assert len(result["aspects"]) > 0
    AnalysisOutput.model_validate(result)


@skip_no_key
def test_analysis_agent_real_llm_positive_review():
    result = analyse_review(MOCK_REVIEW_POSITIVE)

    assert result["status"] == "success", f"Agent returned error: {result.get('error_detail')}"
    assert result["sentiment"] in ("positive", "negative", "neutral", "mixed")
    AnalysisOutput.model_validate(result)


@skip_no_key
def test_reasoning_agent_real_llm():
    result = reason_over_reviews(
        MOCK_REASONING_INPUT["analysis_results"],
        business_id=MOCK_REASONING_INPUT["business_id"],
    )

    assert result["status"] == "success", f"Agent returned error: {result.get('error_detail')}"
    assert isinstance(result["patterns"], list)
    assert isinstance(result["root_causes"], list)
    ReasoningOutput.model_validate(result)


@skip_no_key
def test_analysis_then_reasoning_pipeline():
    """End-to-end: analyse 2 reviews, feed results into reasoning agent."""
    reviews = [MOCK_REVIEW, MOCK_REVIEW_POSITIVE]

    analysis_results = []
    for review in reviews:
        result = analyse_review(review)
        assert result["status"] == "success", f"Analysis failed: {result.get('error_detail')}"
        analysis_results.append({
            "review_id": result["review_id"],
            "sentiment": result["sentiment"],
            "aspects": result["aspects"],
        })

    reasoning_result = reason_over_reviews(analysis_results, business_id="test_biz")

    assert reasoning_result["status"] == "success", (
        f"Reasoning failed: {reasoning_result.get('error_detail')}"
    )
    ReasoningOutput.model_validate(reasoning_result)
