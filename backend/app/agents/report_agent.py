"""Report Generator Agent — builds the final human-readable report.

Supports a deterministic mode (use_llm=False) used by the tests and offline runs,
and an LLM-backed mode (use_llm=True) that uses the configured OpenAI models.
"""

import json
import os

from dotenv import load_dotenv
from pydantic import ValidationError

from app.agents.base_agent import BaseAgent
from app.core import llm_config
from app.schemas.contracts import AgentError, ReportGeneratorInput, ReportOutput

_REPORT_TITLE = "Restaurant Review Analysis Report"

_BASE_LIMITATIONS = [
    "Analysis is based on a random sample of up to 100 reviews and may not represent every customer.",
    "Sentiment and aspect labels are produced automatically and may contain classification errors.",
]

_SYSTEM_PROMPT = """\
You are a business analyst writing a concise report for a restaurant owner.
Given upstream analysis, reasoning, and recommendation outputs, produce a clear report.

Return a JSON object with:
- title: "Restaurant Review Analysis Report"
- business_name: the restaurant name
- sample_size: number of reviews analysed
- executive_summary: a short plain-English summary
- key_findings: list of the most important findings
- root_causes: list of likely root causes
- recommendations: prioritised actions
- limitations: list of caveats about the analysis
- status: "success"
- error_detail: null

Return only valid JSON."""


def _load_environment() -> None:
    load_dotenv()


def _candidate_models() -> list[str]:
    return [
        os.getenv("OPENAI_MODEL", "gemini-2.5-flash"),
        os.getenv("OPENAI_FALLBACK_MODEL", "gemini-3.5-flash"),
    ]


def _error(detail: str) -> dict:
    return {"recommendations": [], "status": "error", "error_detail": detail}


def _build_key_findings(patterns: list[dict]) -> list[str]:
    if not patterns:
        return ["No major recurring pattern was provided by upstream agents."]
    return [p.get("description", "") for p in patterns if p.get("description")]


def _build_executive_summary(business_name: str, sample_size: int, recommendations: list[dict]) -> str:
    if not recommendations:
        return (
            f"This report summarises {sample_size} sampled reviews for {business_name}. "
            "No prioritised recommendations were produced by the upstream agents."
        )
    actions = "; ".join(r.get("action", "") for r in recommendations if r.get("action"))
    return (
        f"Based on {sample_size} sampled reviews for {business_name}, the priority actions are: "
        f"{actions}"
    )


def _build_limitations(sample_size: int) -> list[str]:
    limitations = list(_BASE_LIMITATIONS)
    if sample_size == 0:
        limitations.append(
            "No review records were available for this restaurant, so the findings are limited."
        )
    return limitations


def _deterministic_report(payload: dict) -> dict:
    business_name = payload.get("business_name", "")
    sample_size = payload.get("sample_size", 0)
    reasoning_summary = payload.get("reasoning_summary") or {}
    recommendations = payload.get("recommendations") or []
    patterns = reasoning_summary.get("patterns") or []
    root_causes = reasoning_summary.get("root_causes") or []

    return {
        "title": _REPORT_TITLE,
        "business_name": business_name,
        "sample_size": sample_size,
        "executive_summary": _build_executive_summary(business_name, sample_size, recommendations),
        "key_findings": _build_key_findings(patterns),
        "root_causes": root_causes,
        "recommendations": recommendations,
        "limitations": _build_limitations(sample_size),
        "status": "success",
        "error_detail": None,
    }


class ReportAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__()
        self._model, self._fallback_model = _candidate_models()

    def run(self, input_data: dict, feedback: str | None = None) -> dict:
        original_task = (
            "Generate the final restaurant review analysis report from these "
            f"upstream outputs:\n{json.dumps(input_data, indent=2)}"
        )
        messages = self._with_feedback(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": original_task},
            ],
            feedback,
        )

        result, error, error_type, attempts = self._run_with_retry(
            messages,
            ReportOutput,
            original_task,
        )

        if result is not None:
            result["business_name"] = input_data["business_name"]
            result["sample_size"] = input_data["sample_size"]
            return result

        return AgentError(
            agent="report_agent",
            error_type=error_type or "unknown_error",
            error_detail=error or "Unknown error",
            retry_count=attempts,
            recoverable=False,
        ).model_dump()


def _llm_report(payload: dict, feedback: str | None = None) -> dict:
    return ReportAgent().run(payload, feedback=feedback)


def generate_report(payload: dict, use_llm: bool = True, feedback: str | None = None) -> dict:
    try:
        ReportGeneratorInput.model_validate(payload)
    except ValidationError as exc:
        return _error(f"Invalid report generator input: {exc}")

    if use_llm:
        _load_environment()
        if not llm_config.is_configured():
            return _error("OPENAI_API_KEY is not set.")
        return _llm_report(payload, feedback=feedback)

    return _deterministic_report(payload)
