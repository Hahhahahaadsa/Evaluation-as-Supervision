"""Deterministic supervision for the simple-hub orchestrator (Option B).

Measuring is separate from deciding (ORCHESTRATOR_SIMPLE_HUB.md, P1):

- :func:`measure` computes facts about the stage that just ran, from data
  already in ``PipelineState``. Pure Python, no LLM, no thresholds applied.
- :func:`decide` turns those facts into a verdict
  (``proceed | proceed_with_warning | retry | halt``) using hard rules only.
- :func:`apply_frequency_corrections` overwrites LLM-claimed pattern
  frequencies with the recomputed values — Python knows ``n``, the model
  does not (FINDINGS F2a).

The check definitions deliberately mirror ``eval/tier1_checks.py`` (same
frequency tolerance, same aspect-presence rule, same trace-similarity
threshold) so that what the orchestrator enforces mid-run and what Tier 1
scores offline can never disagree.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

# ── Thresholds (proposals — calibrate against backend/out/, see DECISIONS) ───

MIN_VIABLE_N = 5          # fewer successful analyses than this -> halt
LOW_CONFIDENCE_N = 30     # fewer than this -> proceed_with_warning
CONTRADICTION_MAX = 0.20  # stars-vs-sentiment contradiction rate -> retry
FREQUENCY_TOLERANCE = 0.05  # same as eval/tier1_checks.FREQUENCY_TOLERANCE
TRACE_SIMILARITY = 0.35     # same as eval/tier1_checks._TRACE_SIMILARITY
MAX_RECOVERY_RETRIES = 2    # same as OrchestratorAgent.MAX_RECOVERY_RETRIES

AGENT_SEQUENCE = ["analysis_agent", "reasoning_agent", "strategy_agent", "report_agent"]
CRITICAL_STAGES = {"analysis_agent", "reasoning_agent"}


@dataclass
class Decision:
    verdict: str                      # proceed | proceed_with_warning | retry | halt
    flags: list[str] = field(default_factory=list)
    retry_feedback: str | None = None


# ── Shared helpers ────────────────────────────────────────────────────────────


def _similar(a: str, b: str) -> float:
    # Mirrors eval/tier1_checks._similar so mid-run and offline verdicts agree.
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _records(reviews: Any) -> list[dict]:
    """Best-effort review records from state['reviews_df'] (DataFrame or list)."""
    if reviews is None:
        return []
    to_dict = getattr(reviews, "to_dict", None)
    if callable(to_dict):
        raw = reviews.to_dict(orient="records")
    else:
        try:
            raw = list(reviews)
        except TypeError:
            return []
    return [r for r in raw if isinstance(r, dict)]


def latest_stage(state: dict) -> str | None:
    """The most recent agent stage, inferred from which outputs exist.

    Same backward scan as the old graph._infer_failed_agent — no bookkeeping
    field to go stale.
    """
    if state.get("report_output") is not None:
        return "report_agent"
    if state.get("strategy_output") is not None:
        return "strategy_agent"
    if state.get("reasoning_output") is not None:
        return "reasoning_agent"
    if state.get("analysis_results") is not None:
        return "analysis_agent"
    return None


def next_stage(stage: str) -> str | None:
    try:
        idx = AGENT_SEQUENCE.index(stage)
    except ValueError:
        return None
    return AGENT_SEQUENCE[idx + 1] if idx + 1 < len(AGENT_SEQUENCE) else None


# ── measure ───────────────────────────────────────────────────────────────────


def measure(stage: str, state: dict) -> dict:
    if stage == "analysis_agent":
        return _measure_analysis(state)
    if stage == "reasoning_agent":
        return _measure_reasoning(state)
    if stage == "strategy_agent":
        return _measure_strategy(state)
    if stage == "report_agent":
        return _measure_report(state)
    return {}


def _measure_analysis(state: dict) -> dict:
    results = state.get("analysis_results") or []
    successes = [r for r in results if r.get("status") == "success"]
    failures = [r for r in results if r.get("status") != "success"]

    stars_by_id: dict[str, int] = {}
    for rec in _records(state.get("reviews_df")):
        rid, stars = rec.get("review_id"), rec.get("stars")
        if rid is not None and isinstance(stars, (int, float)):
            stars_by_id[str(rid)] = int(stars)

    contradictions: list[str] = []
    checked = 0
    for r in successes:
        stars = stars_by_id.get(str(r.get("review_id")))
        if stars is None:
            continue
        checked += 1
        sentiment = r.get("sentiment")
        if (stars >= 4 and sentiment == "negative") or (stars <= 2 and sentiment == "positive"):
            contradictions.append(
                f"review {r.get('review_id')}: {stars} stars but labelled '{sentiment}'"
            )

    return {
        "n_loaded": len(results),
        "n_success": len(successes),
        "failure_ratio": len(failures) / len(results) if results else 0.0,
        "failure_details": [f.get("error_detail") or "analysis error" for f in failures[:3]],
        "contradiction_rate": len(contradictions) / checked if checked else None,
        "contradictions": contradictions,
    }


def _measure_reasoning(state: dict) -> dict:
    output = state.get("reasoning_output") or {}
    analysis = state.get("analysis_results") or []
    by_id = {str(a.get("review_id")): a for a in analysis if isinstance(a, dict)}
    success_ids = [rid for rid, a in by_id.items() if a.get("status") == "success"]
    n_success = len(success_ids)

    pattern_facts: list[dict] = []
    for i, pattern in enumerate(output.get("patterns") or []):
        aspect = pattern.get("aspect")
        evidence_ids = pattern.get("evidence_review_ids") or []

        missing = [rid for rid in evidence_ids if rid not in by_id]
        misaligned = [
            rid
            for rid in evidence_ids
            if rid in by_id
            and not any(
                a.get("category") == aspect for a in (by_id[rid].get("aspects") or [])
            )
        ]
        negative_count = sum(
            1
            for rid in success_ids
            if any(
                a.get("category") == aspect and a.get("label") == "negative"
                for a in (by_id[rid].get("aspects") or [])
            )
        )
        pattern_facts.append(
            {
                "index": i,
                "aspect": aspect,
                "description": (pattern.get("description") or "")[:60],
                "missing_evidence_ids": missing,
                "misaligned_evidence_ids": misaligned,
                "claimed_frequency": pattern.get("frequency"),
                "recomputed_frequency": negative_count / n_success if n_success else 0.0,
            }
        )

    return {
        "status_error": output.get("status") == "error",
        "error_detail": output.get("error_detail"),
        "n_success": n_success,
        "patterns": pattern_facts,
    }


def _measure_strategy(state: dict) -> dict:
    output = state.get("strategy_output") or {}
    reasoning = state.get("reasoning_output") or {}
    candidates = (
        [rc.get("cause", "") for rc in reasoning.get("root_causes") or []]
        + [rc.get("pattern", "") for rc in reasoning.get("root_causes") or []]
        + [p.get("description", "") for p in reasoning.get("patterns") or []]
    )

    untraceable: list[str] = []
    for rec in output.get("recommendations") or []:
        issue = rec.get("issue", "")
        best = max((_similar(issue, c) for c in candidates), default=0.0)
        if best < TRACE_SIMILARITY:
            untraceable.append(issue)

    return {
        "status_error": output.get("status") == "error",
        "error_detail": output.get("error_detail"),
        "untraceable_issues": untraceable,
    }


def _measure_report(state: dict) -> dict:
    report = state.get("report_output") or {}
    reasoning = state.get("reasoning_output") or {}
    strategy = state.get("strategy_output") or {}

    upstream_causes = reasoning.get("root_causes") or []
    invented_causes = [
        rc.get("cause", "")
        for rc in report.get("root_causes") or []
        if not any(
            rc.get("cause") == u.get("cause") and rc.get("pattern") == u.get("pattern")
            for u in upstream_causes
        )
    ]

    upstream_recs = strategy.get("recommendations") or []
    invented_recs = [
        r.get("issue", "")
        for r in report.get("recommendations") or []
        if not any(
            r.get("issue") == u.get("issue") and r.get("action") == u.get("action")
            for u in upstream_recs
        )
    ]

    # Metadata is checked only when the report carries the key — mock/partial
    # payloads without it are a schema concern, not a trust concern.
    name_mismatch = (
        "business_name" in report
        and report.get("business_name") != state.get("business_name")
    )
    n_loaded = len(state.get("analysis_results") or [])
    size_mismatch = (
        "sample_size" in report and report.get("sample_size") != n_loaded
    )

    return {
        "status_error": report.get("status") == "error",
        "error_detail": report.get("error_detail"),
        "invented_root_causes": invented_causes,
        "invented_recommendations": invented_recs,
        "name_mismatch": name_mismatch,
        "size_mismatch": size_mismatch,
    }


# ── decide ────────────────────────────────────────────────────────────────────


def decide(stage: str, facts: dict, retry_counts: dict) -> Decision:
    """Hard rules over measured facts. The retry cap gates every retry: once a
    stage has been retried MAX_RECOVERY_RETRIES times, a would-be retry becomes
    ``halt`` (critical stages) or ``proceed_with_warning`` (non-critical), so
    the graph can never loop.
    """
    decision = _quality_rules(stage, facts)
    if decision.verdict != "retry":
        return decision

    if retry_counts.get(stage, 0) >= MAX_RECOVERY_RETRIES:
        gave_up = f"{stage}:gave_up_after_retries"
        if stage in CRITICAL_STAGES or stage == "report_agent":
            return Decision("halt", [gave_up], decision.retry_feedback)
        return Decision("proceed_with_warning", [gave_up], None)
    return decision


def _quality_rules(stage: str, facts: dict) -> Decision:
    if stage == "analysis_agent":
        n = facts["n_success"]
        if n < MIN_VIABLE_N:
            return Decision("halt", [f"insufficient_data:n={n}"],
                            f"only {n} reviews were successfully analysed (minimum {MIN_VIABLE_N})")
        if facts["failure_ratio"] > 0.5:
            return Decision("retry", [], "over half of the reviews failed analysis: "
                            + "; ".join(facts["failure_details"]))
        rate = facts["contradiction_rate"]
        if rate is not None and rate > CONTRADICTION_MAX:
            return Decision("retry", [],
                            f"sentiment labels contradict star ratings in {rate:.0%} of reviews: "
                            + "; ".join(facts["contradictions"][:5]))
        if n < LOW_CONFIDENCE_N:
            return Decision("proceed_with_warning", [f"low_confidence:n={n}"])
        return Decision("proceed")

    if stage == "reasoning_agent":
        if facts["status_error"]:
            return Decision("retry", [], facts.get("error_detail") or "reasoning agent returned an error")
        problems: list[str] = []
        for p in facts["patterns"]:
            if p["missing_evidence_ids"]:
                problems.append(
                    f"pattern '{p['description']}': evidence ids not found in the analysis output: "
                    f"{p['missing_evidence_ids'][:3]}"
                )
            if p["misaligned_evidence_ids"]:
                problems.append(
                    f"pattern '{p['description']}': these evidence reviews do not mention aspect "
                    f"'{p['aspect']}': {p['misaligned_evidence_ids'][:3]}"
                )
        if problems:
            return Decision("retry", [], "your previous output cited unverifiable evidence. "
                            + " | ".join(problems))
        flags = [
            f"frequency_corrected:{p['aspect']}:{p['claimed_frequency']}->{p['recomputed_frequency']:.2f}"
            for p in facts["patterns"]
            if p["claimed_frequency"] is not None
            and abs(p["claimed_frequency"] - p["recomputed_frequency"]) > FREQUENCY_TOLERANCE
        ]
        if flags:
            return Decision("proceed_with_warning", flags)
        return Decision("proceed")

    if stage == "strategy_agent":
        if facts["status_error"]:
            return Decision("retry", [], facts.get("error_detail") or "strategy agent returned an error")
        if facts["untraceable_issues"]:
            return Decision("retry", [],
                            "these recommendation issues do not trace back to any reasoning "
                            f"pattern or root cause: {facts['untraceable_issues'][:3]}")
        return Decision("proceed")

    if stage == "report_agent":
        if facts["status_error"]:
            return Decision("retry", [], facts.get("error_detail") or "report agent returned an error")
        problems = []
        if facts["invented_root_causes"]:
            problems.append(f"root causes not produced upstream: {facts['invented_root_causes'][:3]}")
        if facts["invented_recommendations"]:
            problems.append(f"recommendations not produced upstream: {facts['invented_recommendations'][:3]}")
        if facts["name_mismatch"]:
            problems.append("business_name does not match the pipeline's trusted value")
        if facts["size_mismatch"]:
            problems.append("sample_size does not match the number of analysed reviews")
        if problems:
            return Decision("retry", [], "the report must only restate upstream outputs. "
                            + " | ".join(problems))
        return Decision("proceed")

    return Decision("proceed")


# ── frequency corrections (Python is authoritative — F2a) ────────────────────


def apply_frequency_corrections(reasoning_output: dict, facts: dict) -> list[str]:
    """Overwrite each pattern's claimed frequency with the recomputed value.

    Returns a description of every correction applied (empty when the LLM's
    claims were already within tolerance). Call only on a reasoning-stage
    proceed verdict — a retry means the patterns are about to be regenerated.
    """
    corrections: list[str] = []
    patterns = reasoning_output.get("patterns") or []
    for p_facts in facts.get("patterns", []):
        idx = p_facts["index"]
        if idx >= len(patterns):
            continue
        claimed = p_facts["claimed_frequency"]
        recomputed = round(p_facts["recomputed_frequency"], 3)
        if claimed is None or abs(claimed - recomputed) > 1e-9:
            patterns[idx]["frequency"] = recomputed
            if claimed is None or abs((claimed or 0.0) - recomputed) > FREQUENCY_TOLERANCE:
                corrections.append(
                    f"{p_facts['aspect']}: claimed {claimed} -> recomputed {recomputed}"
                )
    return corrections
