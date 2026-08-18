"""Repetition study: how often does a once-observed defect recur?

Phase A/B assume that a defect seen once reappears when the same input is re-run.
It did not: none of the five businesses flagged in Phase A reproduced its defect
under Phase B enforcement. This script measures the assumption directly by
re-running each flagged business K times in *observe* mode over identical input,
yielding a per-run defect probability conditional on having shown a defect once.

Observe mode is deliberate: supervision measures and records but never acts, so
every repetition is an independent observation of the same pipeline on the same
review set. Nothing about the binary, graph, or checks differs from Phase A --
only the number of times it runs.

Usage (from backend/, venv active):
    MAX_REVIEW_SAMPLE=214 python scripts/run_repetition.py --reps 5

Each repetition writes to out_study/R/rep<k>/A/, the same layout run_study.py
produces, so the existing tally tooling reads it unchanged. Every completed
business is checkpointed, so an interrupted batch resumes where it stopped.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import json  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

from app.core import llm_config  # noqa: E402
from app.data import loader  # noqa: E402

import run_study  # noqa: E402  (sibling module; same scripts/ directory)


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reps", type=int, default=5, help="Repetitions per business.")
    ap.add_argument("--sample", default="out_study/sample.json")
    ap.add_argument("--out", default="out_study")
    ap.add_argument("--ids", nargs="*", default=None,
                    help="Business ids to repeat (default: the Phase A flagged set).")
    ap.add_argument("--sleep", type=float, default=5.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.sample, encoding="utf-8") as fh:
        sample = json.load(fh)
    all_businesses = run_study.businesses_from_sample(sample)

    if not args.dry_run and not llm_config.is_configured():
        print(llm_config.NOT_CONFIGURED_MESSAGE)
        return 1

    if args.ids:
        by_id = {b["business_id"]: b for b in all_businesses}
        targets = [by_id[i] for i in args.ids if i in by_id]
    else:
        targets = run_study.phase_b_targets(args.out, all_businesses)
    if not targets:
        print("Nothing to run.")
        return 1

    # Same guard as run_study: loader.MAX_REVIEWS is read at import, so a missing
    # MAX_REVIEW_SAMPLE silently truncates the large strata instead of failing.
    biggest = max((b.get("review_count") or 0) for b in targets)
    if biggest > loader.MAX_REVIEWS:
        print(f"REFUSING TO RUN: largest target holds {biggest} reviews but the "
              f"effective cap is {loader.MAX_REVIEWS}.")
        print(f"  Fix:  MAX_REVIEW_SAMPLE={biggest} python scripts/run_repetition.py")
        return 1

    print(f"Repetition study — {len(targets)} business(es) x {args.reps} repetition(s) "
          f"in observe mode.")
    for b in targets:
        print(f"  {b.get('stratum'):4s} {b['business_id']} {b.get('name')}")
    print()

    for k in range(1, args.reps + 1):
        out_dir = os.path.join(args.out, "R", f"rep{k}")
        done = run_study.load_checkpoint(out_dir, "A")
        todo = [b for b in targets if b["business_id"] not in done]
        print(f"=== repetition {k}/{args.reps} — {len(done)} done, {len(todo)} to run ===")

        for i, b in enumerate(todo, 1):
            print(f"[{k}.{i}/{len(todo)}] {b.get('stratum')} {b['business_id']} "
                  f"{b.get('name')} ...")
            row = run_study.run_one(b, "A", out_dir, None, args.dry_run)
            row["repetition"] = k
            # A dry run resolves and loads but produces no measurement. Writing it
            # to the checkpoint would make the subsequent real run treat every
            # business as already done and skip the entire batch.
            if not args.dry_run:
                run_study.append_checkpoint(out_dir, "A", row)
            if row.get("status") == "ok":
                print(f"    ok: {row.get('loaded_review_count')} reviews, "
                      f"{row.get('wall_clock_s')}s, "
                      f"would_retry={row.get('would_retry_stages') or '-'}")
            else:
                print(f"    {row.get('status')}: {row.get('error')}")
            if args.sleep:
                time.sleep(args.sleep)

    print("\nRepetition study finished. Checkpoints under "
          f"{os.path.join(args.out, 'R')}/rep*/A/checkpoint.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
