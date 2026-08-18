"""End-to-end pipeline integration test — real graph, real LLM, all 5 stages.

This is the only test that exercises the full multi-agent pipeline as a single
run: preprocess -> analysis -> reasoning -> strategy -> report, driven through
the real LangGraph graph (``app.core.graph.build_graph``) with the real agent
implementations and live LLM calls.

Unlike ``test_graph.py`` (full graph, mocked agents) and ``test_integration.py``
(real LLM, but only analysis -> reasoning), this joins both halves: the actual
graph wiring AND real model output across every stage.

Design notes:
- Uses a small fixed in-memory sample instead of scanning the 5.3 GB Yelp review
  file, so the test is deterministic and does not depend on the dataset files.
- The sample is crafted with a shared wait-time / service complaint so the
  reasoning stage has a genuine recurring pattern to detect.

Run with:
    cd backend
    python -m pytest tests/test_e2e_pipeline.py -v -m integration

Skips automatically when OPENAI_API_KEY is not set.
"""

import os

import pytest
from dotenv import load_dotenv

from app.core.graph import RECURSION_LIMIT, build_graph
from app.core.nodes import (
    analysis_node,
    reasoning_node,
    report_node,
    strategy_node,
)
from app.core.state import PipelineState
from app.schemas.contracts import (
    AnalysisOutput,
    ReasoningOutput,
    ReportOutput,
    StrategyOutput,
)

load_dotenv()

pytestmark = pytest.mark.integration

skip_no_key = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set"
)

BUSINESS_NAME = "E2E Test Diner"
BUSINESS_ID = "e2e-biz-001"

# A small sample with a deliberate shared complaint (slow service / wait time)
# so the reasoning stage finds a recurring pattern across multiple reviews.
SAMPLE_REVIEWS = [
    {
        "review_id": "e2e-1",
        "business_id": BUSINESS_ID,
        "stars": 2,
        "text": "The food was tasty but we waited almost 40 minutes for our mains. Way too slow.",
        "date": "2024-01-05",
    },
    {
        "review_id": "e2e-2",
        "business_id": BUSINESS_ID,
        "stars": 2,
        "text": "Great burgers, but the service was painfully slow and we waited ages to even order.",
        "date": "2024-02-11",
    },
    {
        "review_id": "e2e-3",
        "business_id": BUSINESS_ID,
        "stars": 3,
        "text": "Decent flavours. The wait time was long again though, staff seemed overwhelmed.",
        "date": "2024-03-02",
    },
    {
        "review_id": "e2e-4",
        "business_id": BUSINESS_ID,
        "stars": 5,
        "text": "Loved it! Friendly staff and the meal came out quickly. No complaints at all.",
        "date": "2024-03-20",
    },
    # Six reviews total: the supervising orchestrator halts runs with fewer
    # than supervision.MIN_VIABLE_N (5) successful analyses.
    {
        "review_id": "e2e-5",
        "business_id": BUSINESS_ID,
        "stars": 2,
        "text": "Food is fine but expect to wait. Took nearly half an hour before anyone took our order.",
        "date": "2024-04-08",
    },
    {
        "review_id": "e2e-6",
        "business_id": BUSINESS_ID,
        "stars": 1,
        "text": "Terribly slow service again. The waiting time ruins what could be a good diner.",
        "date": "2024-04-19",
    },
]


# The analysis/reasoning/strategy/report nodes are the shared production
# implementations from app.core.nodes — the same ones the CLI runner and the
# (future) API use. Only the preprocess node is test-specific: it injects the
# fixed in-memory sample instead of loading from the dataset.

def preprocess_node(state: PipelineState) -> PipelineState:
    state["business_id"] = BUSINESS_ID
    state["reviews_df"] = SAMPLE_REVIEWS  # list of review dicts stands in for the DataFrame
    return state


def _initial_state() -> PipelineState:
    return {
        "business_name": BUSINESS_NAME,
        "business_id": None,
        "reviews_df": None,
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


def _invoke_until_complete(graph, attempts: int = 3) -> PipelineState:
    """Run the real-LLM pipeline, retrying on graceful degradation.

    The strategy and report stages are non-critical (see
    ``OrchestratorAgent.CRITICAL_AGENTS``), and every stage — plus the
    orchestrator's own recovery decision — makes live LLM calls that
    occasionally fail schema validation even at temperature 0. When that
    happens the pipeline *correctly* degrades: the orchestrator skips the
    non-critical agent or halts, so a single run can legitimately end as
    "skip"/"halted" with no code bug involved.

    Retrying the whole pipeline keeps the strong "all five stages succeed
    together" assertion below while staying robust to the model's inherent
    per-run failure rate.
    """
    last: PipelineState | None = None
    for _ in range(attempts):
        last = graph.invoke(_initial_state(), {"recursion_limit": RECURSION_LIMIT})
        if last["pipeline_status"] == "complete":
            return last
    pytest.fail(
        f"Pipeline never completed in {attempts} attempts; last status="
        f"{last['pipeline_status']}, skipped_agents={last.get('skipped_agents')}, "
        f"errors={last.get('errors')}"
    )


@skip_no_key
def test_full_pipeline_real_llm_all_stages():
    """Run the real graph end to end through all 5 stages with live LLM calls."""
    graph = build_graph(
        analysis_node=analysis_node,
        reasoning_node=reasoning_node,
        strategy_node=strategy_node,
        report_node=report_node,
        preprocess_node=preprocess_node,
    )

    result = _invoke_until_complete(graph, attempts=3)

    # The pipeline ran all five stages and completed without falling back to the
    # error handler.
    assert result["pipeline_status"] == "complete"
    assert not result.get("skipped_agents"), (
        f"Stages were skipped: {result['skipped_agents']}"
    )

    # Stages 1–2: one analysis result per review, all successful and contract-valid.
    analysis_results = result["analysis_results"]
    assert analysis_results is not None
    assert len(analysis_results) == len(SAMPLE_REVIEWS)
    for a in analysis_results:
        assert a["status"] == "success", f"Analysis failed: {a}"
        AnalysisOutput.model_validate(a)

    # Stages 3–4: reasoning and strategy succeeded and validate against contracts.
    assert result["reasoning_output"]["status"] == "success"
    ReasoningOutput.model_validate(result["reasoning_output"])
    assert result["strategy_output"]["status"] == "success"
    StrategyOutput.model_validate(result["strategy_output"])

    # Stage 5: final report is present and valid. In LLM mode the model generates
    # the whole report JSON, so we assert on structurally guaranteed content
    # rather than exact echoes of the input fields (which are model-controlled).
    report = result["report_output"]
    assert report["status"] == "success", f"Report failed: {report.get('error_detail')}"
    validated = ReportOutput.model_validate(report)
    assert validated.business_name.strip(), "Report is missing a business name"
    assert validated.executive_summary.strip(), "Report is missing an executive summary"
    assert isinstance(validated.recommendations, list)
