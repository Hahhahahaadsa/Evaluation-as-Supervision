"""Build and run the full multi-agent pipeline with the real agent nodes.

This is the single entry point that wires the real graph
(:func:`app.core.graph.build_graph`) with the real node implementations from
:mod:`app.core.nodes`. The CLI runner (``backend/run_pipeline.py``) and the
FastAPI endpoint should both call :func:`run_pipeline`.
"""

from typing import Any, Optional

from app.core.graph import RECURSION_LIMIT, build_graph
from app.core.nodes import (
    analysis_node,
    passthrough_preprocess_node,
    report_node,
    reasoning_node,
    strategy_node,
)
from app.core.state import PipelineState


def build_pipeline():
    """Compile the LangGraph graph with the real agent nodes.

    Uses a passthrough preprocess node — callers are expected to load and clean
    reviews up front and pass them in via ``reviews_df``.
    """
    return build_graph(
        analysis_node=analysis_node,
        reasoning_node=reasoning_node,
        strategy_node=strategy_node,
        report_node=report_node,
        preprocess_node=passthrough_preprocess_node,
    )


def initial_state(
    business_name: str,
    reviews: Any,
    business_id: Optional[str] = None,
) -> PipelineState:
    """Build a fresh PipelineState seeded with the data needed to run.

    ``reviews`` may be a pandas DataFrame or a list of review dicts.
    """
    return {
        "business_name": business_name,
        "business_id": business_id,
        "reviews_df": reviews,
        "analysis_results": None,
        "reasoning_output": None,
        "strategy_output": None,
        "report_output": None,
        "retry_counts": {},
        "skipped_agents": [],
        "errors": {},
        "pipeline_status": "running",
        "failed_agent": None,
        "flags": [],
        "retry_feedback": None,
        "last_verdict": None,
    }


def run_pipeline(
    business_name: str,
    reviews: Any,
    business_id: Optional[str] = None,
) -> PipelineState:
    """Run the full pipeline end to end and return the final state.

    Stages: analysis -> reasoning -> strategy -> report, each followed by the
    orchestrator's deterministic supervision (simple hub). The explicit
    recursion limit is required: with retries, the default of 25 is exactly
    the worst case (see app/core/graph.py).
    """
    graph = build_pipeline()
    return graph.invoke(
        initial_state(business_name, reviews, business_id),
        {"recursion_limit": RECURSION_LIMIT},
    )
