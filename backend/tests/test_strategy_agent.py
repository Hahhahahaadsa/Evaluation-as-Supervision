import json
from unittest.mock import MagicMock, patch

from app.agents.strategy_agent import (
    StrategyAgent,
    _candidate_models,
    generate_recommendations,
)
from app.schemas.contracts import AgentError, StrategyOutput

PATCH_TARGET = "app.agents.base_agent.OpenAI"

STRATEGY_PAYLOAD = {
    "patterns": [
        {
            "description": "Repeated wait-time complaints",
            "aspect": "wait_time",
            "frequency": 0.42,
            "evidence_review_ids": ["r1", "r2"],
        }
    ],
    "root_causes": [
        {
            "pattern": "Repeated wait-time complaints",
            "cause": "Possible staffing issue during busy periods",
            "confidence": "high",
        }
    ],
}

STRATEGY_OUTPUT = {
    "recommendations": [
        {
            "priority": 1,
            "issue": "Possible staffing issue during busy periods",
            "action": "Review peak-hour staffing levels.",
            "category": "operations",
            "expected_impact": "Reduce wait-time complaints",
        }
    ],
    "status": "success",
    "error_detail": None,
}


def make_llm_response(content: dict) -> MagicMock:
    mock = MagicMock()
    mock.choices[0].message.content = json.dumps(content)
    return mock


def test_generate_recommendations_prioritizes_confidence_and_frequency():
    result = generate_recommendations(
        {
            "patterns": [
                {
                    "description": "Repeated wait-time complaints",
                    "aspect": "wait_time",
                    "frequency": 0.42,
                    "evidence_review_ids": ["r1", "r2"],
                },
                {
                    "description": "Pricing complaints",
                    "aspect": "pricing",
                    "frequency": 0.25,
                    "evidence_review_ids": ["r3"],
                },
            ],
            "root_causes": [
                {
                    "pattern": "Pricing complaints",
                    "cause": "Menu prices may not match customer value expectations",
                    "confidence": "medium",
                },
                {
                    "pattern": "Repeated wait-time complaints",
                    "cause": "Possible staffing or table-turnover issue during busy periods",
                    "confidence": "high",
                },
            ],
        },
        use_llm=False,
    )

    assert result["status"] == "success"
    assert result["error_detail"] is None
    assert len(result["recommendations"]) == 2
    assert result["recommendations"][0]["priority"] == 1
    assert result["recommendations"][0]["category"] == "operations"
    assert "staffing" in result["recommendations"][0]["issue"]
    assert result["recommendations"][1]["priority"] == 2
    assert result["recommendations"][1]["category"] == "pricing"


def test_generate_recommendations_allows_empty_root_causes():
    result = generate_recommendations(
        {"patterns": [], "root_causes": []},
        use_llm=False,
    )

    assert result == {
        "recommendations": [],
        "status": "success",
        "error_detail": None,
    }


def test_generate_recommendations_returns_error_for_invalid_input():
    result = generate_recommendations(
        {"patterns": "not-a-list", "root_causes": []},
        use_llm=False,
    )

    assert result["status"] == "error"
    assert result["recommendations"] == []
    assert "Invalid strategic agent input" in result["error_detail"]


def test_generate_recommendations_requires_api_key_for_llm_mode(monkeypatch):
    monkeypatch.setattr("app.agents.strategy_agent._load_environment", lambda: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = generate_recommendations(
        {
            "patterns": [],
            "root_causes": [
                {
                    "pattern": "Repeated wait-time complaints",
                    "cause": "Possible staffing issue",
                    "confidence": "high",
                }
            ],
        },
        use_llm=True,
    )

    assert result["status"] == "error"
    assert result["recommendations"] == []
    assert result["error_detail"] == "OPENAI_API_KEY is not set."


def test_generate_recommendations_llm_retries_invalid_output_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.agents.strategy_agent._load_environment", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with patch(PATCH_TARGET) as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            make_llm_response({"wrong_field": "bad"}),
            make_llm_response(STRATEGY_OUTPUT),
        ]

        result = generate_recommendations(STRATEGY_PAYLOAD, use_llm=True)

    assert result["status"] == "success"
    assert mock_client.chat.completions.create.call_count == 2
    StrategyOutput.model_validate(result)


def test_generate_recommendations_llm_exhausted_retries_returns_agent_error(monkeypatch):
    monkeypatch.setattr("app.agents.strategy_agent._load_environment", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with patch(PATCH_TARGET) as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = make_llm_response(
            {"wrong_field": "bad"}
        )

        result = generate_recommendations(STRATEGY_PAYLOAD, use_llm=True)

    assert result["status"] == "error"
    assert result["agent"] == "strategy_agent"
    assert result["error_type"] == "schema_validation_error"
    assert result["retry_count"] == StrategyAgent.MAX_RETRIES
    assert mock_client.chat.completions.create.call_count == StrategyAgent.MAX_RETRIES + 1
    AgentError.model_validate(result)


def test_candidate_models_use_primary_and_fallback_defaults(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_FALLBACK_MODEL", raising=False)

    assert _candidate_models() == ["gemini-2.5-flash", "gemini-3.5-flash"]


def test_candidate_models_allow_explicit_primary_override(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5")
    monkeypatch.setenv("OPENAI_FALLBACK_MODEL", "gpt-5-mini")

    assert _candidate_models() == ["gpt-5", "gpt-5-mini"]

