"""Unit tests for app.core.supervision — the measure/decide module (PR 1).

Two kinds of coverage:

1. Against the REAL 73-review LOVE Grille dumps in backend/out/ — most
   importantly, the mistyped evidence id ("SKXs-JiPXpVnAwcXhA5wA", one char
   dropped from a 22-char Yelp id) that Tier 1 caught offline must now be
   caught by the supervisor.
2. Synthetic states exercising every decision rule.
"""

import json
from pathlib import Path

import pytest

from app.core import supervision
from app.core.supervision import Decision, decide, measure

OUT_DIR = Path(__file__).resolve().parent.parent / "out"
MISTYPED_ID = "SKXs-JiPXpVnAwcXhA5wA"  # real defect from the 2026-07 live run

needs_dumps = pytest.mark.skipif(
    not (OUT_DIR / "analysis.json").exists() or not (OUT_DIR / "reasoning.json").exists(),
    reason="backend/out/ live dumps not present",
)


def _load(name: str):
    with open(OUT_DIR / f"{name}.json", encoding="utf-8") as fh:
        return json.load(fh)


# ── Against the real live dumps ───────────────────────────────────────────────


@needs_dumps
def test_mistyped_evidence_id_is_caught_mid_run():
    state = {"analysis_results": _load("analysis"), "reasoning_output": _load("reasoning")}
    facts = measure("reasoning_agent", state)

    all_missing = [rid for p in facts["patterns"] for rid in p["missing_evidence_ids"]]
    assert MISTYPED_ID in all_missing

    decision = decide("reasoning_agent", facts, retry_counts={})
    assert decision.verdict == "retry"
    assert MISTYPED_ID in decision.retry_feedback


@needs_dumps
def test_live_frequencies_recompute_within_tolerance():
    """The live run's claimed frequencies were honest (Tier 1: 5/5 within
    ±0.05) — recomputation must agree with tier1_checks' arithmetic."""
    state = {"analysis_results": _load("analysis"), "reasoning_output": _load("reasoning")}
    facts = measure("reasoning_agent", state)

    assert facts["patterns"], "live dump should contain patterns"
    for p in facts["patterns"]:
        assert abs(p["claimed_frequency"] - p["recomputed_frequency"]) <= supervision.FREQUENCY_TOLERANCE


@needs_dumps
def test_live_analysis_measures_cleanly():
    state = {"analysis_results": _load("analysis"), "reviews_df": None}
    facts = measure("analysis_agent", state)
    assert facts["n_loaded"] == 73
    assert facts["n_success"] == 73
    assert facts["failure_ratio"] == 0.0
    assert decide("analysis_agent", facts, {}).verdict == "proceed"


# ── Analysis rules (synthetic) ────────────────────────────────────────────────


def _analysis_state(n_success: int, n_error: int = 0, reviews=None):
    results = [
        {"review_id": f"r{i}", "sentiment": "negative",
         "aspects": [{"category": "wait_time", "label": "negative"}], "status": "success"}
        for i in range(n_success)
    ] + [
        {"status": "error", "error_detail": "boom", "agent": "analysis_agent"}
        for _ in range(n_error)
    ]
    return {"analysis_results": results, "reviews_df": reviews}


def test_insufficient_data_halts():
    facts = measure("analysis_agent", _analysis_state(supervision.MIN_VIABLE_N - 1))
    decision = decide("analysis_agent", facts, {})
    assert decision.verdict == "halt"
    assert any(f.startswith("insufficient_data") for f in decision.flags)


def test_small_sample_proceeds_with_low_confidence_flag():
    n = supervision.LOW_CONFIDENCE_N - 1
    decision = decide("analysis_agent", measure("analysis_agent", _analysis_state(n)), {})
    assert decision.verdict == "proceed_with_warning"
    assert f"low_confidence:n={n}" in decision.flags


def test_majority_failure_retries_with_feedback():
    facts = measure("analysis_agent", _analysis_state(n_success=10, n_error=11))
    decision = decide("analysis_agent", facts, {})
    assert decision.verdict == "retry"
    assert "boom" in decision.retry_feedback


def test_star_contradictions_trigger_retry():
    n = supervision.LOW_CONFIDENCE_N + 10
    state = _analysis_state(n)
    for r in state["analysis_results"]:
        r["sentiment"] = "negative"
    # every review is 5 stars -> 100% contradiction
    state["reviews_df"] = [{"review_id": f"r{i}", "stars": 5} for i in range(n)]
    decision = decide("analysis_agent", measure("analysis_agent", state), {})
    assert decision.verdict == "retry"
    assert "stars but labelled" in decision.retry_feedback


def test_contradiction_rate_none_when_stars_unavailable():
    # mock/preprocessed states may carry no usable stars: never crash, never retry
    state = _analysis_state(supervision.LOW_CONFIDENCE_N + 10, reviews="mock_dataframe")
    facts = measure("analysis_agent", state)
    assert facts["contradiction_rate"] is None
    assert decide("analysis_agent", facts, {}).verdict == "proceed"


def test_retry_cap_halts_critical_stage():
    facts = measure("analysis_agent", _analysis_state(n_success=10, n_error=11))
    decision = decide("analysis_agent", facts, {"analysis_agent": supervision.MAX_RECOVERY_RETRIES})
    assert decision.verdict == "halt"
    assert "analysis_agent:gave_up_after_retries" in decision.flags


# ── Reasoning rules (synthetic) ───────────────────────────────────────────────


def _reasoning_state(patterns, n_reviews=40):
    analysis = [
        {"review_id": f"r{i}", "sentiment": "negative",
         "aspects": [{"category": "wait_time", "label": "negative"}], "status": "success"}
        for i in range(n_reviews)
    ]
    return {
        "analysis_results": analysis,
        "reasoning_output": {"patterns": patterns, "root_causes": [], "status": "success"},
    }


def test_reasoning_status_error_retries():
    state = {"analysis_results": [], "reasoning_output": {"status": "error", "error_detail": "parse fail"}}
    decision = decide("reasoning_agent", measure("reasoning_agent", state), {})
    assert decision.verdict == "retry"
    assert decision.retry_feedback == "parse fail"


def test_fabricated_evidence_id_retries():
    state = _reasoning_state([{
        "description": "waits", "aspect": "wait_time", "frequency": 1.0,
        "evidence_review_ids": ["r0", "r1", "ghost-id"],
    }])
    decision = decide("reasoning_agent", measure("reasoning_agent", state), {})
    assert decision.verdict == "retry"
    assert "ghost-id" in decision.retry_feedback


def test_misaligned_aspect_retries():
    state = _reasoning_state([{
        "description": "dirty tables", "aspect": "cleanliness", "frequency": 0.0,
        "evidence_review_ids": ["r0"],  # r0 only mentions wait_time
    }])
    decision = decide("reasoning_agent", measure("reasoning_agent", state), {})
    assert decision.verdict == "retry"
    assert "cleanliness" in decision.retry_feedback


def test_divergent_frequency_flags_and_corrects_without_retry():
    state = _reasoning_state([{
        "description": "waits", "aspect": "wait_time", "frequency": 0.10,  # truth: 1.0
        "evidence_review_ids": ["r0", "r1"],
    }])
    facts = measure("reasoning_agent", state)
    decision = decide("reasoning_agent", facts, {})
    assert decision.verdict == "proceed_with_warning"
    assert any(f.startswith("frequency_corrected:wait_time") for f in decision.flags)

    corrections = supervision.apply_frequency_corrections(state["reasoning_output"], facts)
    assert state["reasoning_output"]["patterns"][0]["frequency"] == 1.0
    assert len(corrections) == 1


def test_reasoning_retry_cap_halts():
    state = _reasoning_state([{
        "description": "waits", "aspect": "wait_time", "frequency": 1.0,
        "evidence_review_ids": ["ghost-id"],
    }])
    decision = decide(
        "reasoning_agent", measure("reasoning_agent", state),
        {"reasoning_agent": supervision.MAX_RECOVERY_RETRIES},
    )
    assert decision.verdict == "halt"


# ── Strategy rules (synthetic) ────────────────────────────────────────────────


def _strategy_state(issue: str):
    return {
        "reasoning_output": {
            "patterns": [{"description": "Long waits on weekends", "aspect": "wait_time",
                          "frequency": 0.4, "evidence_review_ids": ["r1"]}],
            "root_causes": [{"pattern": "Long waits on weekends", "cause": "Understaffing",
                             "confidence": "medium"}],
            "status": "success",
        },
        "strategy_output": {
            "recommendations": [{"priority": 1, "issue": issue, "action": "do something",
                                 "category": "operations", "expected_impact": "less waiting"}],
            "status": "success",
        },
    }


def test_traceable_recommendation_proceeds():
    decision = decide("strategy_agent", measure("strategy_agent", _strategy_state("Understaffing")), {})
    assert decision.verdict == "proceed"


def test_untraceable_recommendation_retries():
    decision = decide(
        "strategy_agent",
        measure("strategy_agent", _strategy_state("Website checkout latency")),
        {},
    )
    assert decision.verdict == "retry"
    assert "Website checkout latency" in decision.retry_feedback


def test_strategy_retry_cap_degrades_to_warning_not_halt():
    """Non-critical stage: after the cap, continue without it (old 'skip')."""
    decision = decide(
        "strategy_agent",
        measure("strategy_agent", _strategy_state("Website checkout latency")),
        {"strategy_agent": supervision.MAX_RECOVERY_RETRIES},
    )
    assert decision.verdict == "proceed_with_warning"
    assert "strategy_agent:gave_up_after_retries" in decision.flags


# ── Report rules (synthetic) ──────────────────────────────────────────────────


def _report_state(**report_overrides):
    strategy_rec = {"priority": 1, "issue": "Understaffing", "action": "Hire staff",
                    "category": "operations", "expected_impact": "shorter waits"}
    report = {
        "title": "Restaurant Review Analysis Report",
        "business_name": "LOVE Grille",
        "sample_size": 2,
        "executive_summary": "…",
        "key_findings": [],
        "root_causes": [],
        "recommendations": [strategy_rec],
        "limitations": [],
        "status": "success",
        "error_detail": None,
    }
    report.update(report_overrides)
    return {
        "business_name": "LOVE Grille",
        "analysis_results": [{"review_id": "r1", "status": "success", "sentiment": "negative", "aspects": []},
                             {"review_id": "r2", "status": "success", "sentiment": "negative", "aspects": []}],
        "reasoning_output": {"patterns": [], "root_causes": [], "status": "success"},
        "strategy_output": {"recommendations": [strategy_rec], "status": "success"},
        "report_output": report,
    }


def test_faithful_report_proceeds():
    decision = decide("report_agent", measure("report_agent", _report_state()), {})
    assert decision.verdict == "proceed"


def test_invented_recommendation_in_report_retries():
    state = _report_state(recommendations=[{
        "priority": 1, "issue": "Rebrand the logo", "action": "Hire a designer",
        "category": "marketing", "expected_impact": "?"}])
    decision = decide("report_agent", measure("report_agent", state), {})
    assert decision.verdict == "retry"
    assert "Rebrand the logo" in decision.retry_feedback


def test_report_metadata_mismatch_retries():
    state = _report_state(business_name="Some Other Restaurant")
    decision = decide("report_agent", measure("report_agent", state), {})
    assert decision.verdict == "retry"
    assert "business_name" in decision.retry_feedback


def test_report_retry_cap_halts():
    state = _report_state(business_name="Some Other Restaurant")
    decision = decide(
        "report_agent", measure("report_agent", state),
        {"report_agent": supervision.MAX_RECOVERY_RETRIES},
    )
    assert decision.verdict == "halt"


# ── Helpers ───────────────────────────────────────────────────────────────────


def test_latest_stage_scans_backward():
    assert supervision.latest_stage({}) is None
    assert supervision.latest_stage({"analysis_results": []}) == "analysis_agent"
    assert supervision.latest_stage(
        {"analysis_results": [], "reasoning_output": {}}) == "reasoning_agent"
    assert supervision.latest_stage(
        {"analysis_results": [], "reasoning_output": {}, "strategy_output": {},
         "report_output": {}}) == "report_agent"


def test_next_stage_sequence():
    assert supervision.next_stage("analysis_agent") == "reasoning_agent"
    assert supervision.next_stage("report_agent") is None
    assert supervision.next_stage("unknown") is None
