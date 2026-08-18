"""Tier 1b - pipeline harness (needs the API / real graph).

Separate from tier1_checks because these RUN the pipeline rather than score a
static dump:

    - reproducibility     same sample seed -> identical sampled review_ids twice
    - latency & cost      per-stage timing + LLM token counts per 100 reviews
    - degradation         inject malformed / low-quality stage outputs and assert
                          the supervising orchestrator takes the designed
                          proceed / proceed_with_warning / retry / halt path

Run:  python -m eval.harness --name "McDonald's" --pick 1 --runs 3
"""

from __future__ import annotations

import argparse
import sys
import time
from unittest.mock import patch

from app.agents.base_agent import BaseAgent
from app.core import graph as g
from app.core.nodes import analysis_node, reasoning_node, report_node, strategy_node
from app.data import loader, preprocessor


def measure_reproducibility(business_name: str, pick: int, seed: int) -> bool:
    """Assert identical review IDs from two runs with the same sample seed."""
    results = loader.search_business(business_name)
    if not results or not (1 <= pick <= len(results)):
        raise ValueError(f"--pick {pick} out of range for '{business_name}' ({len(results)} matches)")
    business_id = results[pick - 1]["business_id"]

    with patch.object(loader, "RANDOM_SEED", seed):
        ids_1 = set(loader.load_reviews(business_id)["review_id"])
        ids_2 = set(loader.load_reviews(business_id)["review_id"])
    return ids_1 == ids_2 and len(ids_1) > 0


def measure_latency_and_cost(business_name: str, pick: int) -> dict:
    """Time each stage and sum LLM tokens (via BaseAgent.total_tokens_used).

    Runs the real node functions directly (not through the LangGraph error-
    handling wrapper) so a single stage failure doesn't abort the measurement.
    """
    results = loader.search_business(business_name)
    if not results or not (1 <= pick <= len(results)):
        raise ValueError(f"--pick {pick} out of range for '{business_name}' ({len(results)} matches)")
    selected = results[pick - 1]

    df_raw = loader.load_reviews(selected["business_id"])
    df_clean = preprocessor.preprocess(df_raw)
    n_reviews = len(df_clean)
    if n_reviews == 0:
        raise ValueError(f"no reviews available for {selected['name']} - cannot measure latency")

    state = {
        "business_name": selected["name"],
        "business_id": selected["business_id"],
        "reviews_df": df_clean,
        "analysis_results": None,
        "reasoning_output": None,
        "strategy_output": None,
        "report_output": None,
    }

    BaseAgent.reset_token_usage()
    timings: dict[str, float] = {}

    for stage_name, node_fn in (
        ("analysis", analysis_node),
        ("reasoning", reasoning_node),
        ("strategy", strategy_node),
        ("report", report_node),
    ):
        start = time.perf_counter()
        state = node_fn(state)
        timings[stage_name] = time.perf_counter() - start

    total_tokens = BaseAgent.total_tokens_used
    total_time = sum(timings.values())
    scale = 100 / n_reviews

    return {
        "business_name": selected["name"],
        "n_reviews": n_reviews,
        "timings_sec": timings,
        "total_time_sec": total_time,
        "total_time_sec_per_100_reviews": total_time * scale,
        "total_tokens": total_tokens,
        "tokens_per_100_reviews": total_tokens * scale,
    }


def check_degradation_paths() -> list[dict]:
    """Feed malformed / low-quality stage outputs through the supervising
    orchestrator and assert it takes the designed verdict + route. Exercises
    graph.orchestrator_node + graph.route_from_orchestrator as an integration
    pair on the REAL supervision rules — fully deterministic, no LLM call.
    """
    scenarios = []

    def _good_analyses(n: int) -> list[dict]:
        return [
            {"review_id": f"r{i}", "sentiment": "negative",
             "aspects": [{"category": "wait_time", "label": "negative"}],
             "status": "success"}
            for i in range(n)
        ]

    def _run(name: str, state: dict, expect_verdict: str, expect_route: str):
        state.setdefault("errors", {})
        state.setdefault("skipped_agents", [])
        state.setdefault("flags", [])
        result_state = g.orchestrator_node(state)
        route = g.route_from_orchestrator(result_state)
        passed = result_state["last_verdict"] == expect_verdict and route == expect_route
        scenarios.append(
            {
                "scenario": name,
                "expected": {"verdict": expect_verdict, "route": expect_route},
                "actual": {"verdict": result_state["last_verdict"], "route": route},
                "passed": passed,
            }
        )

    # Healthy stage output -> explicit proceed on the record.
    _run(
        "healthy_analysis_proceeds",
        {"analysis_results": _good_analyses(40), "retry_counts": {}},
        expect_verdict="proceed", expect_route="reasoning_agent",
    )

    # Small-but-viable sample -> continues, flagged low_confidence (F1).
    _run(
        "small_sample_flagged_low_confidence",
        {"analysis_results": _good_analyses(13), "retry_counts": {}},
        expect_verdict="proceed_with_warning", expect_route="reasoning_agent",
    )

    # Too little data for any defensible report -> halt.
    _run(
        "insufficient_data_halts",
        {"analysis_results": _good_analyses(3), "retry_counts": {}},
        expect_verdict="halt", expect_route="END",
    )

    # Critical stage, majority of the batch failed, retries remain -> retry.
    _run(
        "critical_majority_failure_retries",
        {"analysis_results": _good_analyses(6)
         + [{"status": "error", "error_detail": "injected"} for _ in range(7)],
         "retry_counts": {}},
        expect_verdict="retry", expect_route="analysis_agent",
    )

    # Same failure with retries exhausted -> halt (critical never degrades silently).
    _run(
        "critical_exhausted_halts",
        {"analysis_results": _good_analyses(6)
         + [{"status": "error", "error_detail": "injected"} for _ in range(7)],
         "retry_counts": {"analysis_agent": 2}},
        expect_verdict="halt", expect_route="END",
    )

    # Reasoning citing nonexistent evidence -> retry with feedback (fabrication gate).
    _run(
        "fabricated_evidence_retries",
        {"analysis_results": _good_analyses(40),
         "reasoning_output": {"patterns": [{"description": "ghost", "aspect": "wait_time",
                                            "frequency": 1.0,
                                            "evidence_review_ids": ["no-such-id"]}],
                              "root_causes": [], "status": "success"},
         "retry_counts": {}},
        expect_verdict="retry", expect_route="reasoning_agent",
    )

    # Non-critical stage broken beyond the cap -> continues ON THE RECORD
    # (flag + skipped_agents), the report still runs.
    _run(
        "noncritical_gave_up_continues_on_record",
        {"analysis_results": _good_analyses(40),
         "reasoning_output": {"patterns": [], "root_causes": [], "status": "success"},
         "strategy_output": {"recommendations": [], "status": "error",
                             "error_detail": "injected"},
         "retry_counts": {"strategy_agent": 2}},
        expect_verdict="proceed_with_warning", expect_route="report_agent",
    )

    # Report broken beyond the cap -> halt (no report = nothing to proceed to).
    _run(
        "report_gave_up_halts",
        {"analysis_results": _good_analyses(40),
         "reasoning_output": {"patterns": [], "root_causes": [], "status": "success"},
         "strategy_output": {"recommendations": [], "status": "success"},
         "report_output": {"status": "error", "error_detail": "injected"},
         "retry_counts": {"report_agent": 2}},
        expect_verdict="halt", expect_route="END",
    )

    return scenarios


def _print_report(repro_ok: bool | None, latency: dict | None, degradation: list[dict]) -> None:
    print("\n=== Tier 1b harness report ===")

    if repro_ok is not None:
        print(f"\nReproducibility: {'PASS' if repro_ok else 'FAIL'}")

    if latency is not None:
        print(f"\nLatency & cost ({latency['n_reviews']} reviews):")
        for stage, secs in latency["timings_sec"].items():
            print(f"  {stage:<10}: {secs:.2f}s")
        print(f"  {'total':<10}: {latency['total_time_sec']:.2f}s "
              f"({latency['total_time_sec_per_100_reviews']:.2f}s / 100 reviews)")
        print(f"  tokens    : {latency['total_tokens']} "
              f"({latency['tokens_per_100_reviews']:.0f} / 100 reviews)")

    print("\nDegradation paths:")
    for s in degradation:
        status = "PASS" if s["passed"] else "FAIL"
        print(f"  [{status}] {s['scenario']}: expected {s['expected']} got {s['actual']}")

    n_pass = sum(1 for s in degradation if s["passed"])
    print(f"\n{n_pass}/{len(degradation)} degradation scenarios passed")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", help="Restaurant name (required for --runs > 0 / latency+repro checks)")
    ap.add_argument("--pick", type=int, default=1)
    ap.add_argument("--runs", type=int, default=3, help="How many times to repeat the reproducibility check")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-live", action="store_true", help="Only run the degradation-path checks (no API/dataset needed)")
    args = ap.parse_args(argv[1:])

    degradation = check_degradation_paths()
    repro_ok = None
    latency = None
    ok = all(s["passed"] for s in degradation)

    if not args.skip_live:
        if not args.name:
            print("--name is required unless --skip-live is set")
            return 2
        repro_ok = all(measure_reproducibility(args.name, args.pick, args.seed) for _ in range(max(1, args.runs)))
        latency = measure_latency_and_cost(args.name, args.pick)
        ok = ok and repro_ok

    _print_report(repro_ok, latency, degradation)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
