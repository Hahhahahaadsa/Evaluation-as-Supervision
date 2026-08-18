"""Strategic Agent — converts patterns and root causes into prioritised actions.

Supports a deterministic mode (use_llm=False) used by the tests and offline runs,
and an LLM-backed mode (use_llm=True) that uses the configured OpenAI models.
"""

import json
import os

from dotenv import load_dotenv
from pydantic import ValidationError

from app.agents.base_agent import BaseAgent
from app.core import llm_config
from app.schemas.contracts import AgentError, StrategicAgentInput, StrategyOutput

_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}

# Maps a review aspect to the business area a recommendation belongs to.
_ASPECT_CATEGORY = {
    "food_quality": "food",
    "staff_attitude": "service",
    "pricing": "pricing",
    "wait_time": "operations",
    "ambience": "ambience",
    "cleanliness": "facilities",
    "other": "general",
}

_SYSTEM_PROMPT = """\
You are a restaurant operations strategist. Given recurring review patterns and
their likely root causes, produce prioritised, concrete business actions.

Return a JSON object with:
- recommendations: list ordered most-important first, each with:
  - priority: integer starting at 1
  - issue: the underlying problem being addressed
  - action: a concrete, specific action the owner can take
  - category: business area (e.g. "operations", "pricing", "service", "food")
  - expected_impact: the improvement expected from the action
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


def _match_pattern(patterns: list[dict], target: str) -> dict | None:
    for pattern in patterns:
        if pattern.get("description") == target:
            return pattern
    return None


def _deterministic_recommendations(patterns: list[dict], root_causes: list[dict]) -> dict:
    ranked = []
    for root_cause in root_causes:
        match = _match_pattern(patterns, root_cause.get("pattern"))
        aspect = match.get("aspect", "other") if match else "other"
        frequency = match.get("frequency", 0.0) if match else 0.0
        ranked.append(
            {
                "issue": root_cause.get("cause", ""),
                "aspect": aspect,
                "category": _ASPECT_CATEGORY.get(aspect, "general"),
                "frequency": frequency,
                "confidence": root_cause.get("confidence", "low"),
            }
        )

    ranked.sort(
        key=lambda r: (_CONFIDENCE_RANK.get(r["confidence"], 0), r["frequency"]),
        reverse=True,
    )

    recommendations = []
    for priority, item in enumerate(ranked, start=1):
        aspect_label = item["aspect"].replace("_", " ")
        recommendations.append(
            {
                "priority": priority,
                "issue": item["issue"],
                "action": f"Address {aspect_label}: {item['issue']}",
                "category": item["category"],
                "expected_impact": f"Reduce {aspect_label} complaints",
            }
        )

    return {"recommendations": recommendations, "status": "success", "error_detail": None}


class StrategyAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__()
        self._model, self._fallback_model = _candidate_models()

    def run(self, input_data: dict, feedback: str | None = None) -> dict:
        original_task = (
            "Generate prioritised restaurant business recommendations from "
            f"these patterns and root causes:\n{json.dumps(input_data, indent=2)}"
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
            StrategyOutput,
            original_task,
        )

        if result is not None:
            return result

        return AgentError(
            agent="strategy_agent",
            error_type=error_type or "unknown_error",
            error_detail=error or "Unknown error",
            retry_count=attempts,
            recoverable=False,
        ).model_dump()


def _llm_recommendations(payload: dict, feedback: str | None = None) -> dict:
    return StrategyAgent().run(payload, feedback=feedback)


def generate_recommendations(
    payload: dict, use_llm: bool = True, feedback: str | None = None
) -> dict:
    try:
        StrategicAgentInput.model_validate(payload)
    except ValidationError as exc:
        return _error(f"Invalid strategic agent input: {exc}")

    patterns = payload.get("patterns", [])
    root_causes = payload.get("root_causes", [])

    if use_llm:
        _load_environment()
        if not llm_config.is_configured():
            return _error("OPENAI_API_KEY is not set.")
        return _llm_recommendations(payload, feedback=feedback)

    return _deterministic_recommendations(patterns, root_causes)
