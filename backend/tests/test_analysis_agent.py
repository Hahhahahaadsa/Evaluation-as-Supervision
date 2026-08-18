import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.analysis_agent import AnalysisAgent, analyse_review, analyse_reviews
from app.agents.reasoning_agent import ReasoningAgent, reason_over_reviews
from app.schemas.contracts import AgentError, AnalysisOutput, ReasoningOutput
from tests.mock_data import (
    MOCK_ANALYSIS_OUTPUT,
    MOCK_ANALYSIS_OUTPUT_POSITIVE,
    MOCK_INVALID_LLM_OUTPUT,
    MOCK_REASONING_INPUT,
    MOCK_REASONING_OUTPUT,
    MOCK_REASONING_OUTPUT_EMPTY_EVIDENCE,
    MOCK_REASONING_OUTPUT_FREQUENCY_OUT_OF_RANGE,
    MOCK_REVIEW,
    MOCK_REVIEW_POSITIVE,
)

PATCH_TARGET = "app.agents.base_agent.OpenAI"


def make_llm_response(content: dict) -> MagicMock:
    mock = MagicMock()
    mock.choices[0].message.content = json.dumps(content)
    return mock


# ── Analysis Agent ────────────────────────────────────────────────────────────

class TestAnalysisAgent:
    @patch(PATCH_TARGET)
    def test_happy_path_negative_review(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = make_llm_response(MOCK_ANALYSIS_OUTPUT)

        result = analyse_review(MOCK_REVIEW)

        assert result["status"] == "success"
        assert result["review_id"] == "abc123"
        assert result["sentiment"] == "negative"
        assert len(result["aspects"]) > 0
        AnalysisOutput.model_validate(result)

    @patch(PATCH_TARGET)
    def test_happy_path_positive_review(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = make_llm_response(MOCK_ANALYSIS_OUTPUT_POSITIVE)

        result = analyse_review(MOCK_REVIEW_POSITIVE)

        assert result["status"] == "success"
        assert result["sentiment"] == "positive"
        AnalysisOutput.model_validate(result)

    @patch(PATCH_TARGET)
    def test_retries_on_invalid_output_then_succeeds(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            make_llm_response(MOCK_INVALID_LLM_OUTPUT),
            make_llm_response(MOCK_ANALYSIS_OUTPUT),
        ]

        result = analyse_review(MOCK_REVIEW)

        assert result["status"] == "success"
        assert mock_client.chat.completions.create.call_count == 2

    @patch(PATCH_TARGET)
    def test_exhausted_retries_returns_agent_error(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = make_llm_response(MOCK_INVALID_LLM_OUTPUT)

        result = analyse_review(MOCK_REVIEW)

        assert result["status"] == "error"
        assert result["agent"] == "analysis_agent"
        assert result["error_type"] == "schema_validation_error"
        assert result["retry_count"] == AnalysisAgent.MAX_RETRIES
        assert mock_client.chat.completions.create.call_count == AnalysisAgent.MAX_RETRIES + 1
        AgentError.model_validate(result)


    @patch(PATCH_TARGET)
    def test_api_exception_returns_agent_error(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("connection timeout")

        result = analyse_review(MOCK_REVIEW)

        assert result["status"] == "error"
        assert result["agent"] == "analysis_agent"
        assert result["error_type"] == "api_error"
        assert result["recoverable"] is False  # agent exhausted all options
        assert "connection timeout" in result["error_detail"]
        AgentError.model_validate(result)

    @patch(PATCH_TARGET)
    def test_batch_retries_until_review_ids_match_input_order(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        valid = {
            "analyses": [
                {**MOCK_ANALYSIS_OUTPUT, "review_id": "r1"},
                {**MOCK_ANALYSIS_OUTPUT_POSITIVE, "review_id": "r2"},
            ]
        }
        mock_client.chat.completions.create.side_effect = [
            make_llm_response({"analyses": valid["analyses"][:1]}),
            make_llm_response({"analyses": list(reversed(valid["analyses"]))}),
            make_llm_response(valid),
        ]

        result = analyse_reviews([
            {**MOCK_REVIEW, "review_id": "r1"},
            {**MOCK_REVIEW_POSITIVE, "review_id": "r2"},
        ])

        assert [item["review_id"] for item in result] == ["r1", "r2"]
        assert mock_client.chat.completions.create.call_count == 3


# ── Reasoning Agent ───────────────────────────────────────────────────────────

class TestReasoningAgent:
    @patch(PATCH_TARGET)
    def test_happy_path(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = make_llm_response(MOCK_REASONING_OUTPUT)

        result = ReasoningAgent().run(MOCK_REASONING_INPUT)

        assert result["status"] == "success"
        assert len(result["patterns"]) > 0
        assert len(result["root_causes"]) > 0
        ReasoningOutput.model_validate(result)

    @patch(PATCH_TARGET)
    def test_business_id_passed_through_wrapper(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = make_llm_response(MOCK_REASONING_OUTPUT)

        result = reason_over_reviews(
            MOCK_REASONING_INPUT["analysis_results"],
            business_id="biz456",
        )

        assert result["status"] == "success"
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        user_message = next(m["content"] for m in messages if m["role"] == "user")
        assert "biz456" in user_message

    @patch(PATCH_TARGET)
    def test_retries_on_invalid_output_then_succeeds(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            make_llm_response(MOCK_INVALID_LLM_OUTPUT),
            make_llm_response(MOCK_REASONING_OUTPUT),
        ]

        result = ReasoningAgent().run(MOCK_REASONING_INPUT)

        assert result["status"] == "success"
        assert mock_client.chat.completions.create.call_count == 2

    @patch(PATCH_TARGET)
    def test_exhausted_retries_returns_agent_error(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = make_llm_response(MOCK_INVALID_LLM_OUTPUT)

        result = ReasoningAgent().run(MOCK_REASONING_INPUT)

        assert result["status"] == "error"
        assert result["agent"] == "reasoning_agent"
        assert result["retry_count"] == ReasoningAgent.MAX_RETRIES
        assert mock_client.chat.completions.create.call_count == ReasoningAgent.MAX_RETRIES + 1
        AgentError.model_validate(result)

    @patch(PATCH_TARGET)
    def test_frequency_out_of_range_triggers_correction(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            make_llm_response(MOCK_REASONING_OUTPUT_FREQUENCY_OUT_OF_RANGE),
            make_llm_response(MOCK_REASONING_OUTPUT),
        ]

        result = ReasoningAgent().run(MOCK_REASONING_INPUT)

        assert result["status"] == "success"
        assert mock_client.chat.completions.create.call_count == 2
        for pattern in result["patterns"]:
            assert 0.0 <= pattern["frequency"] <= 1.0

    @patch(PATCH_TARGET)
    def test_empty_evidence_review_ids_triggers_correction(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            make_llm_response(MOCK_REASONING_OUTPUT_EMPTY_EVIDENCE),
            make_llm_response(MOCK_REASONING_OUTPUT),
        ]

        result = ReasoningAgent().run(MOCK_REASONING_INPUT)

        assert result["status"] == "success"
        assert mock_client.chat.completions.create.call_count == 2
        for pattern in result["patterns"]:
            assert len(pattern["evidence_review_ids"]) >= 1
