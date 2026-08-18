import json

from app.agents.base_agent import BaseAgent
from app.schemas.contracts import AgentError, AnalysisBatchOutput, AnalysisOutput

_SYSTEM_PROMPT = """\
You are a restaurant review analyst. Given a single review, return a JSON object with:

- review_id: the review's ID (string)
- sentiment: overall sentiment — one of "positive", "negative", "neutral", "mixed"
- aspects: list of aspects explicitly mentioned or clearly implied in the review, each with:
  - category: one of "food_quality", "staff_attitude", "pricing", "wait_time", "ambience", "cleanliness", "other"
  - label: sentiment for that aspect — one of "positive", "negative", "neutral"
- status: "success"
- error_detail: null

Only include aspects that are actually present in the review. Return only valid JSON."""

_BATCH_SYSTEM_PROMPT = """\
You are a restaurant review analyst. You are given a LIST of reviews. Analyse EVERY
review and return a JSON object with a single key "analyses": a list with exactly one
object per input review, in the same order, each object with:

- review_id: the review's ID (string), copied exactly from the input
- sentiment: overall sentiment — one of "positive", "negative", "neutral", "mixed"
- aspects: list of aspects explicitly mentioned or clearly implied in the review, each with:
  - category: one of "food_quality", "staff_attitude", "pricing", "wait_time", "ambience", "cleanliness", "other"
  - label: sentiment for that aspect — one of "positive", "negative", "neutral"
- status: "success"
- error_detail: null

Only include aspects that are actually present in a review. Do not skip or merge
reviews — there must be exactly one analysis per input review. Return only valid JSON."""


class AnalysisAgent(BaseAgent):
    def run(self, input_data: dict) -> dict:
        original_task = (
            f"Analyse the following restaurant review and return structured JSON:\n"
            f"{json.dumps(input_data, indent=2)}"
        )
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": original_task},
        ]

        result, error, error_type, attempts = self._run_with_retry(messages, AnalysisOutput, original_task)

        if result is not None:
            return result

        return AgentError(
            agent="analysis_agent",
            error_type=error_type or "unknown_error",
            error_detail=error or "Unknown error",
            retry_count=attempts,
            recoverable=False,
        ).model_dump()

    def run_batch(self, reviews: list[dict], feedback: str | None = None) -> list[dict]:
        """Analyse several reviews in a single LLM call.

        Returns one result dict per input review (success analyses or, if the
        whole batch failed, an AgentError per review so downstream counts stay
        aligned with the number of reviews submitted).

        ``feedback`` carries the orchestrator's retry_feedback when this batch
        is a supervised re-run.
        """
        if not reviews:
            return []

        original_task = (
            f"Analyse the following {len(reviews)} restaurant reviews and return "
            f"structured JSON:\n{json.dumps(reviews, indent=2)}"
        )
        messages = self._with_feedback(
            [
                {"role": "system", "content": _BATCH_SYSTEM_PROMPT},
                {"role": "user", "content": original_task},
            ],
            feedback,
        )

        expected_ids = [str(review["review_id"]) for review in reviews]

        def validate_batch(output: dict) -> None:
            actual_ids = [analysis["review_id"] for analysis in output["analyses"]]
            if actual_ids != expected_ids:
                raise ValueError(
                    f"analysis review IDs must equal input order: expected {expected_ids}, got {actual_ids}"
                )

        result, error, error_type, attempts = self._run_with_retry(
            messages, AnalysisBatchOutput, original_task, validate_batch
        )

        if result is not None:
            return result["analyses"]

        return [
            AgentError(
                agent="analysis_agent",
                error_type=error_type or "unknown_error",
                error_detail=error or "Unknown error",
                retry_count=attempts,
                recoverable=False,
            ).model_dump()
            for _ in reviews
        ]


def analyse_review(review: dict) -> dict:
    return AnalysisAgent().run(review)


def analyse_reviews(reviews: list[dict], feedback: str | None = None) -> list[dict]:
    """Batch entry point — analyse a list of reviews in one LLM call."""
    return AnalysisAgent().run_batch(reviews, feedback=feedback)
