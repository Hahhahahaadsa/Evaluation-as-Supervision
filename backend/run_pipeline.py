"""Interactive CLI: run the full multi-agent pipeline on a real restaurant.

Flow:
    restaurant name -> fuzzy search -> pick a match -> load + sample reviews
    -> analysis -> reasoning -> strategy -> report -> print the report.

Usage (from the backend/ directory, with the venv active):
    python run_pipeline.py
    python run_pipeline.py --name "McDonald's"          # skip the name prompt
    python run_pipeline.py --name "McDonald's" --pick 1 # fully non-interactive
    python run_pipeline.py --name "McDonald's" --pick 1 --dump-stages out/

Requires OPENAI_API_KEY (the agents make real LLM calls). The dataset files must
be present under backend/data/raw/ (see RUN_TESTS.md / README).
"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from app.core import llm_config
from app.core.pipeline import run_pipeline
from app.data import loader, preprocessor


def _choose_match(results: list[dict], pick: int | None) -> dict | None:
    print()
    for i, r in enumerate(results, start=1):
        print(
            f"{i}. {r['name']} - {r.get('address', '')}, {r.get('city', '')}, "
            f"{r.get('state', '')} (reviews={r.get('review_count', 0)}, "
            f"score={r.get('score')}, id={r['business_id']})"
        )

    if pick is not None:
        if not 1 <= pick <= len(results):
            print(f"--pick {pick} is out of range (1-{len(results)}).")
            return None
        return results[pick - 1]

    while True:
        try:
            choice = int(input(f"\nSelect a match (1-{len(results)}): "))
            if 1 <= choice <= len(results):
                return results[choice - 1]
            print(f"Please enter a number from 1 to {len(results)}.")
        except ValueError:
            print("Please enter a number.")
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return None


def _print_report(report: dict) -> None:
    print("\n" + "=" * 70)
    print(report.get("title", "Report"))
    print("=" * 70)
    print(f"Business     : {report.get('business_name', '')}")
    print(f"Sample size  : {report.get('sample_size', 0)} reviews")
    print(f"\nExecutive summary:\n  {report.get('executive_summary', '')}")

    findings = report.get("key_findings") or []
    if findings:
        print("\nKey findings:")
        for f in findings:
            print(f"  - {f}")

    causes = report.get("root_causes") or []
    if causes:
        print("\nLikely root causes:")
        for c in causes:
            print(f"  - [{c.get('confidence', '?')}] {c.get('cause', '')}")

    recs = report.get("recommendations") or []
    if recs:
        print("\nRecommendations (prioritised):")
        for r in recs:
            print(f"  {r.get('priority', '?')}. {r.get('action', '')}")
            print(f"     issue: {r.get('issue', '')} | impact: {r.get('expected_impact', '')}")

    limitations = report.get("limitations") or []
    if limitations:
        print("\nLimitations:")
        for limitation in limitations:
            print(f"  - {limitation}")
    print("=" * 70)


def _run_config() -> dict:
    """Approved provider/model configuration actually used for this run.

    P1 resolution: one approved configuration (primary gemini-2.5-flash,
    fallback gemini-3.5-flash via Gemini's OpenAI-compatible endpoint) is
    recorded into every evaluation dump so results are attributable to a known
    provider/model rather than to whatever a local .env happened to set.
    """
    return llm_config.run_config()


def _dump_stages(final_state: dict, out_dir: str) -> None:
    """Write each agent phase's JSON output to <out_dir> for inspection/demo.

    Pulls the per-stage payloads straight out of the final pipeline state, so it
    captures whatever each agent produced - including a skipped/None stage or an
    ``status: "error"`` payload - which is exactly what you want when debugging
    which phase degraded.
    """
    os.makedirs(out_dir, exist_ok=True)

    stages = {
        "analysis": final_state.get("analysis_results"),
        "reasoning": final_state.get("reasoning_output"),
        "strategy": final_state.get("strategy_output"),
        "report": final_state.get("report_output"),
    }
    summary = {
        "business_name": final_state.get("business_name"),
        "business_id": final_state.get("business_id"),
        "run_config": _run_config(),
        "pipeline_status": final_state.get("pipeline_status"),
        "skipped_agents": final_state.get("skipped_agents"),
        "failed_agent": final_state.get("failed_agent"),
        "errors": final_state.get("errors"),
        "retry_counts": final_state.get("retry_counts"),
        "flags": final_state.get("flags"),
        "last_verdict": final_state.get("last_verdict"),
    }

    for name, payload in {"_summary": summary, **stages}.items():
        path = os.path.join(out_dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        state = "missing" if payload is None else "ok"
        print(f"  wrote {path} ({state})")


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run the full review-analysis pipeline.")
    parser.add_argument("--name", help="Restaurant name (skips the prompt).")
    parser.add_argument(
        "--business-id",
        help="Exact business id (skips name search entirely; reproducible).",
    )
    parser.add_argument("--pick", type=int, help="Auto-select the Nth match (1-based).")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help=f"Review sample size (1-{loader.MAX_REVIEWS}; default: {loader.MAX_REVIEWS}).",
    )
    parser.add_argument("--json", action="store_true", help="Print the raw report JSON.")
    parser.add_argument(
        "--dump-stages",
        metavar="DIR",
        help="Write each agent phase's JSON (analysis/reasoning/strategy/report + _summary) to DIR.",
    )
    args = parser.parse_args()
    if args.sample_size is not None and not 1 <= args.sample_size <= loader.MAX_REVIEWS:
        parser.error(f"--sample-size must be between 1 and {loader.MAX_REVIEWS}")

    if not llm_config.is_configured():
        print(llm_config.NOT_CONFIGURED_MESSAGE)
        return 1

    if args.business_id:
        selected = loader.get_business(args.business_id)
        if selected is None:
            print(f"No business with id {args.business_id!r}.")
            return 1
    else:
        business_name = args.name or input("Restaurant name: ")

        print("Searching businesses...")
        results = loader.search_business(business_name)
        if not results:
            print("No matching business found.")
            return 1

        selected = _choose_match(results, args.pick)
        if selected is None:
            return 1
    print(f"\n>> Selected: {selected['name']} ({selected['business_id']})")

    print("Loading reviews...")
    df_raw = loader.load_reviews(selected["business_id"], args.sample_size)
    if df_raw.empty:
        print("No reviews found for that business. Stopping.")
        return 1

    df_clean = preprocessor.preprocess(df_raw)
    print(f"Running pipeline on {len(df_clean)} reviews (this makes live LLM calls)...")

    final_state = run_pipeline(
        business_name=selected["name"],
        reviews=df_clean,
        business_id=selected["business_id"],
    )

    status = final_state["pipeline_status"]
    print(f"\nPipeline status: {status}")
    if final_state.get("skipped_agents"):
        print(f"Skipped stages : {final_state['skipped_agents']}")

    if args.dump_stages:
        print(f"\nDumping per-stage JSON to {args.dump_stages}/ ...")
        _dump_stages(final_state, args.dump_stages)

    report = final_state.get("report_output")
    if not report or report.get("status") != "success":
        print("No successful report was produced.")
        if report:
            print(f"Report error: {report.get('error_detail')}")
        return 2

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
