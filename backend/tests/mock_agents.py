# tests/mock_agents.py
#
# Mock nodes for graph-shape tests. Under the simple hub the orchestrator
# MEASURES every stage output (app/core/supervision.py), so these mocks must
# be internally consistent, not just schema-shaped:
#   - 6 reviews clears MIN_VIABLE_N (5); stars=2 matches the negative labels
#     so the stars-vs-sentiment contradiction check stays quiet;
#   - reasoning evidence ids exist in the analysis output and carry the
#     claimed aspect; frequency 1.0 matches the recomputed value;
#   - the strategy issue traces verbatim to a reasoning root cause.
from app.core.state import PipelineState

MOCK_REVIEWS = [
    {"review_id": f"r{i}", "stars": 2, "text": "Waited forever for food.", "date": "2026-01-01"}
    for i in range(1, 7)
]


def mock_preprocess(state: PipelineState) -> PipelineState:
    state["business_id"] = "fake-biz-001"
    state["reviews_df"] = MOCK_REVIEWS
    return state


def mock_analysis_agent(state: PipelineState) -> PipelineState:
    state["analysis_results"] = [
        {"review_id": f"r{i}", "sentiment": "negative",
         "aspects": [{"category": "wait_time", "label": "negative"}],
         "status": "success"}
        for i in range(1, 7)
    ]
    return state


def mock_reasoning_agent(state: PipelineState) -> PipelineState:
    state["reasoning_output"] = {
        "patterns": [{"description": "Long waits on weekends", "aspect": "wait_time",
                      "frequency": 1.0, "evidence_review_ids": ["r1", "r2", "r3"]}],
        "root_causes": [{"pattern": "Long waits on weekends", "cause": "Understaffing",
                         "confidence": "medium"}],
        "status": "success",
    }
    return state


def mock_strategy_agent(state: PipelineState) -> PipelineState:
    state["strategy_output"] = {
        "recommendations": [{"priority": 1, "issue": "Understaffing",
                             "action": "Hire 2 weekend staff", "category": "operations",
                             "expected_impact": "Shorter waits"}],
        "status": "success",
    }
    return state


def mock_report_agent(state: PipelineState) -> PipelineState:
    # pipeline_status is set by the orchestrator on the report verdict,
    # not by the report node.
    state["report_output"] = {"html": "<h1>Report</h1>", "status": "success"}
    return state
