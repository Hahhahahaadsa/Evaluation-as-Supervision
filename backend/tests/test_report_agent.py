import json
from unittest.mock import MagicMock, patch

from app.agents.report_agent import (
    ReportAgent,
    _candidate_models,
    generate_report,
)
from app.schemas.contracts import AgentError, ReportOutput

PATCH_TARGET = "app.agents.base_agent.OpenAI"

REPORT_PAYLOAD = {
    "business_name": "Example Restaurant",
    "sample_size": 3,
    "analysis_summary": {},
    "reasoning_summary": {
        "patterns": [
            {
                "description": "Wait-time complaints appear repeatedly.",
                "aspect": "wait_time",
                "frequency": 0.67,
                "evidence_review_ids": ["r1", "r2"],
            }
        ],
        "root_causes": [
            {
                "pattern": "Wait-time complaints appear repeatedly.",
                "cause": "Possible staffing issue during peak periods",
                "confidence": "high",
            }
        ],
    },
    "recommendations": [
        {
            "priority": 1,
            "issue": "Possible staffing issue during peak periods",
            "action": "Review peak-hour staffing levels.",
            "category": "operations",
            "expected_impact": "Reduce wait-time complaints",
        }
    ],
}

REPORT_OUTPUT = {
    "title": "Restaurant Review Analysis Report",
    "business_name": "Example Restaurant",
    "sample_size": 3,
    "executive_summary": "Wait times are the main recurring issue.",
    "key_findings": ["Wait-time complaints appear repeatedly."],
    "root_causes": [
        {
            "pattern": "Wait-time complaints appear repeatedly.",
            "cause": "Possible staffing issue during peak periods",
            "confidence": "high",
        }
    ],
    "recommendations": REPORT_PAYLOAD["recommendations"],
    "limitations": ["Analysis is based on a small sampled review set."],
    "status": "success",
    "error_detail": None,
}


def make_llm_response(content: dict) -> MagicMock:
    mock = MagicMock()
    mock.choices[0].message.content = json.dumps(content)
    return mock


def test_generate_report_builds_deterministic_report():
    result = generate_report(
        {
            "business_name": "Example Restaurant",
            "sample_size": 100,
            "analysis_summary": {
                "sentiment_distribution": {
                    "positive": 55,
                    "neutral": 20,
                    "negative": 25,
                },
                "top_aspects": ["wait_time", "pricing"],
            },
            "reasoning_summary": {
                "patterns": [
                    {
                        "description": "Wait-time complaints appear repeatedly.",
                        "aspect": "wait_time",
                        "frequency": 0.42,
                        "evidence_review_ids": ["r1", "r2"],
                    }
                ],
                "root_causes": [
                    {
                        "pattern": "Repeated wait-time complaints",
                        "cause": "Possible staffing or table-turnover issue during busy periods",
                        "confidence": "high",
                    }
                ],
            },
            "recommendations": [
                {
                    "priority": 1,
                    "issue": "Possible staffing or table-turnover issue during busy periods",
                    "action": "Review peak-hour staffing and table assignment workflow.",
                    "category": "operations",
                    "expected_impact": "Reduce wait-time complaints",
                }
            ],
        },
        use_llm=False,
    )

    assert result["status"] == "success"
    assert result["error_detail"] is None
    assert result["title"] == "Restaurant Review Analysis Report"
    assert result["business_name"] == "Example Restaurant"
    assert result["sample_size"] == 100
    assert "Review peak-hour staffing" in result["executive_summary"]
    assert result["root_causes"][0]["confidence"] == "high"
    assert result["recommendations"][0]["priority"] == 1
    assert result["limitations"]


def test_generate_report_handles_empty_upstream_outputs():
    result = generate_report(
        {
            "business_name": "Empty Restaurant",
            "sample_size": 0,
            "analysis_summary": {},
            "reasoning_summary": {},
            "recommendations": [],
        },
        use_llm=False,
    )

    assert result["status"] == "success"
    assert result["recommendations"] == []
    assert result["root_causes"] == []
    assert result["key_findings"] == [
        "No major recurring pattern was provided by upstream agents."
    ]
    assert "No review records" in result["limitations"][-1]


def test_generate_report_returns_error_for_invalid_input():
    result = generate_report(
        {
            "business_name": "Bad Input Restaurant",
            "sample_size": -1,
            "analysis_summary": {},
            "reasoning_summary": {},
            "recommendations": [],
        },
        use_llm=False,
    )

    assert result["status"] == "error"
    assert result["recommendations"] == []
    assert "Invalid report generator input" in result["error_detail"]


def test_generate_report_requires_api_key_for_llm_mode(monkeypatch):
    monkeypatch.setattr("app.agents.report_agent._load_environment", lambda: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = generate_report(
        {
            "business_name": "Example Restaurant",
            "sample_size": 10,
            "analysis_summary": {},
            "reasoning_summary": {},
            "recommendations": [],
        },
        use_llm=True,
    )

    assert result["status"] == "error"
    assert result["recommendations"] == []
    assert result["error_detail"] == "OPENAI_API_KEY is not set."


def test_generate_report_llm_retries_invalid_output_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.agents.report_agent._load_environment", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with patch(PATCH_TARGET) as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            make_llm_response({"wrong_field": "bad"}),
            make_llm_response(REPORT_OUTPUT),
        ]

        result = generate_report(REPORT_PAYLOAD, use_llm=True)

    assert result["status"] == "success"
    assert mock_client.chat.completions.create.call_count == 2
    ReportOutput.model_validate(result)


def test_generate_report_overwrites_model_metadata(monkeypatch):
    monkeypatch.setattr("app.agents.report_agent._load_environment", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    wrong_metadata = {**REPORT_OUTPUT, "business_name": "Wrong", "sample_size": 999}

    with patch(PATCH_TARGET) as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = make_llm_response(wrong_metadata)
        result = generate_report(REPORT_PAYLOAD, use_llm=True)

    assert result["business_name"] == REPORT_PAYLOAD["business_name"]
    assert result["sample_size"] == REPORT_PAYLOAD["sample_size"]


def test_generate_report_llm_exhausted_retries_returns_agent_error(monkeypatch):
    monkeypatch.setattr("app.agents.report_agent._load_environment", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with patch(PATCH_TARGET) as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = make_llm_response(
            {"wrong_field": "bad"}
        )

        result = generate_report(REPORT_PAYLOAD, use_llm=True)

    assert result["status"] == "error"
    assert result["agent"] == "report_agent"
    assert result["error_type"] == "schema_validation_error"
    assert result["retry_count"] == ReportAgent.MAX_RETRIES
    assert mock_client.chat.completions.create.call_count == ReportAgent.MAX_RETRIES + 1
    AgentError.model_validate(result)


def test_report_candidate_models_use_configured_primary_and_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5")
    monkeypatch.setenv("OPENAI_FALLBACK_MODEL", "gpt-5-mini")

    assert _candidate_models() == ["gpt-5", "gpt-5-mini"]

