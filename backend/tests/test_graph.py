# tests/test_graph.py — simple-hub graph behaviour with mocked agent nodes.
from app.core import supervision
from app.core.graph import RECURSION_LIMIT, build_graph
from app.core.state import PipelineState
from tests.mock_agents import (
    mock_analysis_agent,
    mock_preprocess,
    mock_reasoning_agent,
    mock_report_agent,
    mock_strategy_agent,
)

_CONFIG = {"recursion_limit": RECURSION_LIMIT}


def _initial_state() -> PipelineState:
    return {
        "business_name": "McDonald's",
        "business_id": None, "reviews_df": None,
        "analysis_results": None, "reasoning_output": None,
        "strategy_output": None, "report_output": None,
        "retry_counts": {}, "skipped_agents": [],
        "errors": {}, "pipeline_status": "running", "failed_agent": None,
        "flags": [], "retry_feedback": None, "last_verdict": None,
    }


def _build(**overrides):
    nodes = {
        "analysis_node": mock_analysis_agent,
        "reasoning_node": mock_reasoning_agent,
        "strategy_node": mock_strategy_agent,
        "report_node": mock_report_agent,
        "preprocess_node": mock_preprocess,
    }
    nodes.update(overrides)
    return build_graph(**nodes)


def test_happy_path():
    result = _build().invoke(_initial_state(), _CONFIG)

    assert result["pipeline_status"] == "complete"
    assert result["report_output"]["status"] == "success"
    assert result["last_verdict"] == "proceed"
    assert result["retry_counts"] == {}
    assert result["skipped_agents"] == []
    # n=6 successful analyses < LOW_CONFIDENCE_N -> the run completes but the
    # small sample is on the record.
    assert f"low_confidence:n=6" in result["flags"]


def test_retry_reruns_failed_stage_with_feedback():
    """A stage-level error triggers ONE re-run of that stage, and the re-run
    receives the orchestrator's feedback (temperature-0 reruns without changed
    input would reproduce the identical output)."""
    calls = {"count": 0, "feedback_seen": []}

    def flaky_reasoning(state):
        calls["count"] += 1
        calls["feedback_seen"].append(state.get("retry_feedback"))
        state["retry_feedback"] = None  # node contract: consume on read
        if calls["count"] == 1:
            state["reasoning_output"] = {"patterns": [], "root_causes": [],
                                         "status": "error", "error_detail": "parse fail"}
        else:
            mock_reasoning_agent(state)
        return state

    result = _build(reasoning_node=flaky_reasoning).invoke(_initial_state(), _CONFIG)

    assert calls["count"] == 2
    assert calls["feedback_seen"][0] is None
    assert "parse fail" in calls["feedback_seen"][1]
    assert result["retry_counts"]["reasoning_agent"] == 1
    assert result["pipeline_status"] == "complete"


def test_insufficient_data_halts():
    def tiny_analysis(state):
        state["analysis_results"] = [
            {"review_id": f"r{i}", "sentiment": "negative",
             "aspects": [], "status": "success"}
            for i in range(supervision.MIN_VIABLE_N - 1)
        ]
        return state

    result = _build(analysis_node=tiny_analysis).invoke(_initial_state(), _CONFIG)

    assert result["pipeline_status"] == "halted"
    assert result["failed_agent"] == "analysis_agent"
    assert "analysis_agent" in result["errors"]
    assert result["report_output"] is None  # nothing downstream ran


def test_noncritical_stage_gave_up_is_recorded_not_silent():
    """Strategy failing beyond the retry cap continues WITH a flag and a
    skipped_agents entry (the old silent 'skip', now on the record)."""
    calls = {"count": 0}

    def broken_strategy(state):
        calls["count"] += 1
        state["strategy_output"] = {"recommendations": [], "status": "error",
                                    "error_detail": "always broken"}
        return state

    result = _build(strategy_node=broken_strategy).invoke(_initial_state(), _CONFIG)

    assert calls["count"] == 1 + supervision.MAX_RECOVERY_RETRIES
    assert result["skipped_agents"] == ["strategy_agent"]
    assert "strategy_agent:gave_up_after_retries" in result["flags"]
    # the pipeline still finished: report ran on partial data
    assert result["pipeline_status"] == "complete"
    assert result["report_output"]["status"] == "success"


def test_fabricated_evidence_is_rejected_then_halts_at_cap():
    """Reasoning that keeps citing nonexistent evidence ids exhausts its
    retries and halts the (critical) pipeline."""
    calls = {"count": 0}

    def fabricating_reasoning(state):
        calls["count"] += 1
        state["retry_feedback"] = None
        state["reasoning_output"] = {
            "patterns": [{"description": "ghost pattern", "aspect": "wait_time",
                          "frequency": 1.0, "evidence_review_ids": ["no-such-id"]}],
            "root_causes": [], "status": "success",
        }
        return state

    result = _build(reasoning_node=fabricating_reasoning).invoke(_initial_state(), _CONFIG)

    assert calls["count"] == 1 + supervision.MAX_RECOVERY_RETRIES
    assert result["pipeline_status"] == "halted"
    assert result["failed_agent"] == "reasoning_agent"
