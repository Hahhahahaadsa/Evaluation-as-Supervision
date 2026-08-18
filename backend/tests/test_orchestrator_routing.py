"""Tests for orchestrator criticality and simple-hub routing.

These cover only the deterministic hard-rule and routing logic — no LLM calls.
"""

from app.core import nodes, supervision
from app.core import graph as g
from app.core.orchestrator import OrchestratorAgent
from app.core.pipeline import build_pipeline, initial_state

orchestrator = OrchestratorAgent()


# ── Criticality is suffix-insensitive ─────────────────────────────────────────

def test_is_critical_matches_both_name_forms():
    assert orchestrator.is_critical("analysis") is True
    assert orchestrator.is_critical("analysis_agent") is True
    assert orchestrator.is_critical("REASONING_AGENT") is True
    assert orchestrator.is_critical("strategy_agent") is False
    assert orchestrator.is_critical("report") is False


# ── Legacy recovery API (kept until the team removes it) ─────────────────────

def test_hard_rule_halts_critical_and_skips_noncritical_when_exhausted():
    assert orchestrator.decide_recovery("analysis_agent", "boom", retry_count=2) == "halt"
    assert orchestrator.decide_recovery("strategy_agent", "boom", retry_count=2) == "skip"


def test_provider_failure_uses_deterministic_recovery(monkeypatch):
    class BrokenLLM:
        def invoke(self, _messages):
            raise RuntimeError("provider unavailable")

    local = OrchestratorAgent()
    monkeypatch.setattr(local, "_get_llm", lambda: BrokenLLM())

    assert local.decide_recovery("analysis_agent", "boom", retry_count=0) == "retry"
    assert local.decide_recovery("analysis_agent", "boom", retry_count=2) == "halt"
    assert local.decide_recovery("strategy_agent", "boom", retry_count=2) == "skip"


# ── OrchestratorAgent.decide(state): hub supervision, no LLM ─────────────────

def test_decide_measures_the_latest_stage():
    state = {
        "analysis_results": [
            {"review_id": f"r{i}", "sentiment": "negative",
             "aspects": [{"category": "wait_time", "label": "negative"}],
             "status": "success"}
            for i in range(supervision.LOW_CONFIDENCE_N)
        ],
        "retry_counts": {},
    }
    assert orchestrator.decide(state).verdict == "proceed"

    state["reasoning_output"] = {"patterns": [], "root_causes": [],
                                 "status": "error", "error_detail": "boom"}
    decision = orchestrator.decide(state)
    assert decision.verdict == "retry"
    assert decision.retry_feedback == "boom"


# ── route_from_orchestrator ───────────────────────────────────────────────────

def test_retry_routes_back_to_the_stage_that_just_ran():
    state = {"last_verdict": "retry", "analysis_results": [], "reasoning_output": {}}
    assert g.route_from_orchestrator(state) == "reasoning_agent"


def test_proceed_routes_to_the_next_stage():
    state = {"last_verdict": "proceed", "analysis_results": [], "reasoning_output": {}}
    assert g.route_from_orchestrator(state) == "strategy_agent"


def test_proceed_with_warning_also_advances():
    state = {"last_verdict": "proceed_with_warning", "analysis_results": []}
    assert g.route_from_orchestrator(state) == "reasoning_agent"


def test_proceed_on_report_ends_pipeline():
    state = {"last_verdict": "proceed", "analysis_results": [],
             "reasoning_output": {}, "strategy_output": {}, "report_output": {}}
    assert g.route_from_orchestrator(state) == "END"


def test_halt_ends_pipeline():
    state = {"last_verdict": "halt", "analysis_results": []}
    assert g.route_from_orchestrator(state) == "END"


# ── Full-graph chained recovery with the real supervision rules ──────────────

def test_chained_failures_retry_with_feedback_and_terminate(monkeypatch):
    """reasoning fails once (retried with feedback, then succeeds); strategy
    fails persistently (retried to the cap, then abandoned on the record);
    report succeeds — the pipeline completes with the degradation visible."""
    reasoning_feedback: list = []
    strategy_calls = {"count": 0}

    monkeypatch.setattr(
        nodes,
        "analyse_reviews",
        lambda batch, feedback=None: [
            {
                "review_id": review["review_id"],
                "sentiment": "negative",
                "aspects": [{"category": "wait_time", "label": "negative"}],
                "status": "success",
                "error_detail": None,
            }
            for review in batch
        ],
    )

    def fake_reasoning(_results, business_id, feedback=None):
        reasoning_feedback.append(feedback)
        if len(reasoning_feedback) == 1:
            return {"status": "error", "error_detail": "reasoning failed"}
        return {"status": "success", "error_detail": None, "patterns": [], "root_causes": []}

    monkeypatch.setattr(nodes, "reason_over_reviews", fake_reasoning)

    def fake_strategy(*_args, **_kwargs):
        strategy_calls["count"] += 1
        return {"status": "error", "error_detail": "strategy failed", "recommendations": []}

    monkeypatch.setattr(nodes, "generate_recommendations", fake_strategy)
    monkeypatch.setattr(
        nodes,
        "generate_report",
        lambda *_args, **_kwargs: {"status": "success", "error_detail": None},
    )

    reviews = [
        {"review_id": f"r{i}", "stars": 2, "text": "slow", "date": "2024-01-01"}
        for i in range(supervision.MIN_VIABLE_N + 1)
    ]
    result = build_pipeline().invoke(
        initial_state("Test", reviews, "b1"), {"recursion_limit": g.RECURSION_LIMIT}
    )

    # reasoning: first run blind, second run carries the failure detail
    assert reasoning_feedback[0] is None
    assert "reasoning failed" in reasoning_feedback[1]

    # strategy: initial run + MAX retries, then abandoned on the record
    assert strategy_calls["count"] == 1 + supervision.MAX_RECOVERY_RETRIES
    assert result["skipped_agents"] == ["strategy_agent"]
    assert "strategy_agent:gave_up_after_retries" in result["flags"]

    assert result["pipeline_status"] == "complete"
    assert result["failed_agent"] is None
    assert result["retry_counts"]["reasoning_agent"] == 1
    assert result["retry_counts"]["strategy_agent"] == supervision.MAX_RECOVERY_RETRIES
