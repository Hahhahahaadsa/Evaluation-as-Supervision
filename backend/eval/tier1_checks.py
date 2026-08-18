"""Tier 1 - deterministic checks (no labels, no API). CI-runnable.

Consumes a ``--dump-stages`` directory and returns a list[CheckResult].
Each stage's output is derivable from the previous one, so most correctness
questions reduce to consistency checks that need no ground truth.

Run:  python -m eval.tier1_checks <dump_dir>
"""

from __future__ import annotations

import difflib
import json
import os
import sys

from pydantic import ValidationError

from app.schemas.contracts import (
    AnalysisOutput,
    ReasoningOutput,
    ReportOutput,
    StrategyOutput,
)
from eval.common import CheckResult, LoadedDump, load_dump, print_scorecard

# Tolerance for the recomputed-vs-claimed frequency comparison (Reasoning).
FREQUENCY_TOLERANCE = 0.05

# Minimum text-similarity ratio (difflib) for a strategy/report claim to count
# as "traceable" to an upstream pattern/root-cause/recommendation.
_TRACE_SIMILARITY = 0.35


def _similar(a: str, b: str) -> float:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# ── Schema validity ──────────────────────────────────────────────────────────


def check_schema_validity(dump: LoadedDump) -> list[CheckResult]:
    """Re-validate each non-null stage payload against app.schemas.contracts.

    For analysis (a list), this reports a pass-rate (one bad item shouldn't
    mask nine good ones). The Literal types in contracts.py double as the
    'enum compliance' check - a hallucinated sentiment/category value fails
    validation here.
    """
    results: list[CheckResult] = []

    if dump.analysis is None:
        results.append(
            CheckResult("schema_validity:analysis", True, None, "stage skipped/absent - nothing to validate")
        )
    else:
        total = len(dump.analysis)
        failures: list[str] = []
        for item in dump.analysis:
            try:
                AnalysisOutput.model_validate(item)
            except ValidationError as exc:
                rid = item.get("review_id", "?") if isinstance(item, dict) else "?"
                failures.append(f"{rid}: {exc.errors()[0]['msg']}")
        n_ok = total - len(failures)
        rate = n_ok / total if total else 1.0
        results.append(
            CheckResult(
                "schema_validity:analysis",
                len(failures) == 0,
                rate,
                "all valid" if not failures else f"{len(failures)}/{total} invalid: " + "; ".join(failures[:3]),
            )
        )

    for name, payload, model in (
        ("reasoning", dump.reasoning, ReasoningOutput),
        ("strategy", dump.strategy, StrategyOutput),
        ("report", dump.report, ReportOutput),
    ):
        if payload is None:
            results.append(
                CheckResult(f"schema_validity:{name}", True, None, "stage skipped/absent - nothing to validate")
            )
            continue
        try:
            model.model_validate(payload)
            results.append(CheckResult(f"schema_validity:{name}", True, None, "valid"))
        except ValidationError as exc:
            results.append(
                CheckResult(f"schema_validity:{name}", False, None, f"invalid: {exc.errors()[0]['msg']}")
            )

    return results


# ── Reasoning groundedness ───────────────────────────────────────────────────


def check_reasoning_groundedness(dump: LoadedDump) -> list[CheckResult]:
    """For every Pattern: (a) each evidence_review_id exists in analysis,
    (b) that review actually carries the pattern's aspect, (c) the claimed
    frequency matches the frequency recomputed from analysis within
    FREQUENCY_TOLERANCE.
    """
    if dump.reasoning is None:
        return [CheckResult("reasoning_groundedness", True, None, "reasoning stage skipped/absent")]
    if dump.analysis is None:
        return [CheckResult("reasoning_groundedness", False, None, "reasoning present but analysis missing - cannot ground it")]

    analysis_by_id: dict[str, dict] = {a.get("review_id"): a for a in dump.analysis if isinstance(a, dict)}
    successful_ids = [rid for rid, a in analysis_by_id.items() if a.get("status") == "success"]
    total_success = len(successful_ids)

    patterns = dump.reasoning.get("patterns") or []
    if not patterns:
        return [CheckResult("reasoning_groundedness", True, None, "no patterns claimed - vacuously grounded")]

    results: list[CheckResult] = []
    for i, pattern in enumerate(patterns):
        pname = pattern.get("description", f"pattern[{i}]")[:40]
        aspect = pattern.get("aspect")
        evidence_ids = pattern.get("evidence_review_ids") or []

        # (a) evidence ids exist
        missing_ids = [rid for rid in evidence_ids if rid not in analysis_by_id]
        if missing_ids:
            results.append(
                CheckResult(
                    f"groundedness:{pname}:evidence_exists",
                    False,
                    1 - len(missing_ids) / len(evidence_ids) if evidence_ids else 0.0,
                    f"evidence_review_ids not found in analysis: {missing_ids[:3]}",
                )
            )
        else:
            results.append(CheckResult(f"groundedness:{pname}:evidence_exists", True, 1.0, "all evidence ids found"))

        # (b) each evidence review actually carries the pattern's aspect
        carries = 0
        checked = 0
        for rid in evidence_ids:
            review = analysis_by_id.get(rid)
            if review is None:
                continue
            checked += 1
            aspects = review.get("aspects") or []
            if any(a.get("category") == aspect for a in aspects):
                carries += 1
        if checked == 0:
            results.append(
                CheckResult(f"groundedness:{pname}:aspect_present", False, 0.0, "no resolvable evidence to check")
            )
        else:
            rate = carries / checked
            results.append(
                CheckResult(
                    f"groundedness:{pname}:aspect_present",
                    carries == checked,
                    rate,
                    f"{carries}/{checked} evidence reviews actually carry aspect '{aspect}'",
                )
            )

        # (c) claimed frequency vs recomputed frequency
        # Recomputed as: share of *successfully analysed* reviews whose aspects
        # list carries this aspect with a NEGATIVE label (matches the reasoning
        # agent's own definition: "reviews that mention this aspect negatively").
        if total_success == 0:
            results.append(CheckResult(f"groundedness:{pname}:frequency", False, None, "no successful analyses to recompute frequency from"))
            continue
        negative_count = sum(
            1
            for rid in successful_ids
            if any(a.get("category") == aspect and a.get("label") == "negative" for a in (analysis_by_id[rid].get("aspects") or []))
        )
        recomputed = negative_count / total_success
        claimed = pattern.get("frequency")
        diff = abs((claimed or 0.0) - recomputed)
        passed = diff <= FREQUENCY_TOLERANCE
        results.append(
            CheckResult(
                f"groundedness:{pname}:frequency",
                passed,
                max(0.0, 1 - diff),
                f"claimed={claimed}, recomputed={recomputed:.2f} (tolerance={FREQUENCY_TOLERANCE})",
            )
        )

    return results


# ── Strategy traceability ────────────────────────────────────────────────────


def check_strategy_traceability(dump: LoadedDump) -> list[CheckResult]:
    """Each Recommendation.issue traces to a reasoning pattern / root cause,
    and priority ordering correlates with pattern frequency.
    """
    if dump.strategy is None:
        return [CheckResult("strategy_traceability", True, None, "strategy stage skipped/absent")]

    recommendations = dump.strategy.get("recommendations") or []
    if not recommendations:
        return [CheckResult("strategy_traceability", True, None, "no recommendations claimed - vacuously traceable")]

    root_causes = (dump.reasoning or {}).get("root_causes") or []
    patterns = (dump.reasoning or {}).get("patterns") or []
    if dump.reasoning is None:
        return [CheckResult("strategy_traceability", False, None, "strategy present but reasoning missing - cannot trace it")]

    # (a) traceability: each recommendation.issue should resemble some upstream
    # root_cause.cause / root_cause.pattern / pattern.description.
    candidate_texts = [rc.get("cause", "") for rc in root_causes] + [rc.get("pattern", "") for rc in root_causes] + [p.get("description", "") for p in patterns]

    traced = 0
    best_match_pattern_freq: dict[int, float] = {}
    for rec in recommendations:
        issue = rec.get("issue", "")
        best = max((_similar(issue, c) for c in candidate_texts), default=0.0)
        if best >= _TRACE_SIMILARITY:
            traced += 1
        # find the best-matching root cause -> its pattern -> frequency, for the ordering check
        best_rc_idx, best_rc_score = None, 0.0
        for i, rc in enumerate(root_causes):
            score = max(_similar(issue, rc.get("cause", "")), _similar(issue, rc.get("pattern", "")))
            if score > best_rc_score:
                best_rc_score, best_rc_idx = score, i
        if best_rc_idx is not None and best_rc_score >= _TRACE_SIMILARITY:
            rc = root_causes[best_rc_idx]
            match = next((p for p in patterns if p.get("description") == rc.get("pattern")), None)
            if match is not None:
                best_match_pattern_freq[rec.get("priority", 0)] = match.get("frequency", 0.0)

    rate = traced / len(recommendations)
    results = [
        CheckResult(
            "strategy_traceability:issue_traced",
            traced == len(recommendations),
            rate,
            f"{traced}/{len(recommendations)} recommendation issues trace back to a reasoning pattern/root cause",
        )
    ]

    # (b) priority ordering correlates with pattern frequency (soft check:
    # fraction of adjacent priority pairs that are non-increasing in frequency).
    ordered_freqs = [best_match_pattern_freq[p] for p in sorted(best_match_pattern_freq)]
    if len(ordered_freqs) >= 2:
        correct_pairs = sum(1 for a, b in zip(ordered_freqs, ordered_freqs[1:]) if a >= b - FREQUENCY_TOLERANCE)
        total_pairs = len(ordered_freqs) - 1
        pair_rate = correct_pairs / total_pairs
        results.append(
            CheckResult(
                "strategy_traceability:priority_order",
                pair_rate >= 0.5,
                pair_rate,
                f"{correct_pairs}/{total_pairs} adjacent priority pairs are frequency-ordered (higher priority = higher frequency)",
            )
        )
    else:
        results.append(
            CheckResult("strategy_traceability:priority_order", True, None, "fewer than 2 traced recommendations - ordering not checkable")
        )

    return results


# ── Report subset ────────────────────────────────────────────────────────────


def check_report_subset(dump: LoadedDump) -> list[CheckResult]:
    """report.root_causes / recommendations are subsets of upstream (exact);
    key_findings reference only aspects present upstream (soft).
    """
    if dump.report is None:
        return [CheckResult("report_subset", True, None, "report stage skipped/absent")]

    results: list[CheckResult] = []

    # root_causes subset of reasoning.root_causes
    upstream_causes = (dump.reasoning or {}).get("root_causes") or []
    report_causes = dump.report.get("root_causes") or []
    if report_causes:
        matched = sum(1 for rc in report_causes if any(rc.get("cause") == u.get("cause") and rc.get("pattern") == u.get("pattern") for u in upstream_causes))
        rate = matched / len(report_causes)
        results.append(
            CheckResult(
                "report_subset:root_causes",
                matched == len(report_causes),
                rate,
                f"{matched}/{len(report_causes)} report root causes found verbatim upstream",
            )
        )
    else:
        results.append(CheckResult("report_subset:root_causes", True, None, "report cites no root causes"))

    # recommendations subset of strategy.recommendations
    upstream_recs = (dump.strategy or {}).get("recommendations") or []
    report_recs = dump.report.get("recommendations") or []
    if report_recs:
        matched = sum(1 for r in report_recs if any(r.get("issue") == u.get("issue") and r.get("action") == u.get("action") for u in upstream_recs))
        rate = matched / len(report_recs)
        results.append(
            CheckResult(
                "report_subset:recommendations",
                matched == len(report_recs),
                rate,
                f"{matched}/{len(report_recs)} report recommendations found verbatim upstream",
            )
        )
    else:
        results.append(CheckResult("report_subset:recommendations", True, None, "report cites no recommendations"))

    # key_findings: soft check - each finding should resemble an upstream pattern description
    upstream_patterns = [p.get("description", "") for p in (dump.reasoning or {}).get("patterns") or []]
    findings = dump.report.get("key_findings") or []
    if findings and upstream_patterns:
        grounded = sum(1 for f in findings if max((_similar(f, p) for p in upstream_patterns), default=0.0) >= _TRACE_SIMILARITY)
        rate = grounded / len(findings)
        results.append(
            CheckResult(
                "report_subset:key_findings",
                rate >= 0.5,
                rate,
                f"{grounded}/{len(findings)} key findings resemble an upstream pattern (soft check, threshold {_TRACE_SIMILARITY})",
            )
        )
    else:
        results.append(CheckResult("report_subset:key_findings", True, None, "no findings/patterns to cross-check"))

    return results


# ── Completion status ────────────────────────────────────────────────────────


def check_completion_status(dump: LoadedDump) -> list[CheckResult]:
    """Read pipeline_status / skipped_agents / failed_agent from _summary."""
    status = dump.summary.get("pipeline_status")
    skipped = dump.summary.get("skipped_agents") or []
    failed = dump.summary.get("failed_agent")

    passed = status == "complete"
    detail = f"status={status}"
    if skipped:
        detail += f", skipped={skipped}"
    if failed:
        detail += f", failed_agent={failed}"

    return [CheckResult("completion_status", passed, 1.0 if passed else 0.0, detail)]


# ── Runner ────────────────────────────────────────────────────────────────────


def run_all(dump_dir: str) -> list[CheckResult]:
    dump = load_dump(dump_dir)
    results: list[CheckResult] = []
    for fn in (
        check_schema_validity,
        check_reasoning_groundedness,
        check_strategy_traceability,
        check_report_subset,
        check_completion_status,
    ):
        results.extend(fn(dump))
    return results


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m eval.tier1_checks <dump_dir>")
        return 2
    dump_dir = argv[1]
    results = run_all(dump_dir)
    print_scorecard(results)

    report_path = os.path.join(dump_dir, "tier1_report.json")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(
            [
                {"name": r.name, "passed": r.passed, "score": r.score, "detail": r.detail}
                for r in results
            ],
            fh,
            indent=2,
        )
    print(f"\nwrote {report_path}")

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
