"""Batch runner for the two-phase supervision study (build item 4).

Phase A (observe)  — every business in the sample, SUPERVISION_MODE=observe.
                     Supervision measures and records but never retries, so the
                     run is an unsupervised pipeline with full instrumentation.
                     Yields defect incidence (paper Table 6).
Phase B (enforce)  — only the businesses where Phase A recorded a would-be
                     retry, SUPERVISION_MODE=enforce. Yields repair rate
                     (paper Table 7).

The asymmetry is deliberate and is argued in the paper's Method section: where
Phase A detected nothing, the two arms are identical by construction, so a
second arm there would burn compute without producing evidence.

Checkpointing: every completed business appends one JSON line to
``<out>/<phase>/checkpoint.jsonl``. Re-running skips business ids already
present, so an interrupted batch resumes where it stopped. Rate limits, not
cost, are the binding constraint (~300 LLM calls for a 20-business sample).

Usage (from backend/, venv active):
    python scripts/sample_businesses.py --out out_study/sample.json
    python scripts/run_study.py --phase A --sample out_study/sample.json
    python scripts/run_study.py --phase B --sample out_study/sample.json
    python scripts/run_study.py --phase A --dry-run     # no LLM calls

Both phases write per-business stage dumps to
``<out>/<phase>/<business_id>/``, which is exactly the layout
``eval/tier1_checks.run_all(dump_dir)`` already consumes.
"""

import argparse
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The repository path contains non-ASCII characters and the Windows console
# defaults to cp1252, which cannot encode them. Force UTF-8 on our streams so a
# two-hour batch cannot die on a print().
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


from dotenv import load_dotenv  # noqa: E402

from app.core import graph as graph_mod  # noqa: E402
from app.core import llm_config  # noqa: E402
from app.data import loader, preprocessor  # noqa: E402

PHASES = {"A": "observe", "B": "enforce"}


# ── checkpointing ────────────────────────────────────────────────────────────

def _checkpoint_path(out_dir: str, phase: str) -> str:
    return os.path.join(out_dir, phase, "checkpoint.jsonl")


def load_checkpoint(out_dir: str, phase: str) -> dict[str, dict]:
    path = _checkpoint_path(out_dir, phase)
    done: dict[str, dict] = {}
    if not os.path.exists(path):
        return done
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate a torn final line from a hard kill
            if row.get("business_id"):
                done[row["business_id"]] = row
    return done


def append_checkpoint(out_dir: str, phase: str, row: dict) -> None:
    path = _checkpoint_path(out_dir, phase)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())  # survive a kill between businesses


# ── one business ─────────────────────────────────────────────────────────────

def dump_state(state: dict, out_dir: str, extra: dict) -> None:
    os.makedirs(out_dir, exist_ok=True)
    payloads = {
        "analysis": state.get("analysis_results"),
        "reasoning": state.get("reasoning_output"),
        "strategy": state.get("strategy_output"),
        "report": state.get("report_output"),
        "_summary": {
            "business_name": state.get("business_name"),
            "business_id": state.get("business_id"),
            "run_config": llm_config.run_config(),
            "pipeline_status": state.get("pipeline_status"),
            "skipped_agents": state.get("skipped_agents"),
            "failed_agent": state.get("failed_agent"),
            "errors": state.get("errors"),
            "retry_counts": state.get("retry_counts"),
            "flags": state.get("flags"),
            "last_verdict": state.get("last_verdict"),
            "observations": state.get("observations"),
            **extra,
        },
    }
    for name, payload in payloads.items():
        with open(os.path.join(out_dir, f"{name}.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)


def run_one(business: dict, phase: str, out_dir: str, sample_size: int | None, dry_run: bool) -> dict:
    bid = business["business_id"]
    mode = PHASES[phase]
    started = time.time()

    row: dict = {
        "business_id": bid,
        "business_name": business.get("name"),
        "stratum": business.get("stratum"),
        "expected_review_count": business.get("review_count"),
        "phase": phase,
        "mode": mode,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    try:
        df_raw = loader.load_reviews(bid, sample_size)
        if df_raw.empty:
            row.update(status="error", error="no reviews loaded", wall_clock_s=0.0)
            return row
        df_clean = preprocessor.preprocess(df_raw)
        row["loaded_review_count"] = len(df_clean)

        if dry_run:
            row.update(status="dry-run", wall_clock_s=round(time.time() - started, 2))
            return row

        os.environ[graph_mod.SUPERVISION_MODE_ENV] = mode
        # Imported lazily so --dry-run needs no API key configured.
        from app.core.pipeline import run_pipeline

        state = run_pipeline(
            business_name=business.get("name") or bid,
            reviews=df_clean,
            business_id=bid,
        )
        elapsed = round(time.time() - started, 2)

        observations = state.get("observations") or []
        row.update(
            status="ok",
            wall_clock_s=elapsed,
            pipeline_status=state.get("pipeline_status"),
            retry_counts=state.get("retry_counts") or {},
            flags=state.get("flags") or [],
            skipped_agents=state.get("skipped_agents") or [],
            observations=observations,
            would_retry_stages=sorted(
                {o["stage"] for o in observations if o.get("would_be_verdict") == "retry"}
            ),
            report_ok=bool(
                (state.get("report_output") or {}).get("status") == "success"
            ),
            # Token accounting is NOT yet instrumented anywhere in the codebase.
            # Paper Table 8 needs it; see the note at the bottom of this file.
            total_tokens=None,
        )
        dump_state(state, os.path.join(out_dir, phase, bid), {
            "phase": phase, "mode": mode, "wall_clock_s": elapsed,
            "stratum": business.get("stratum"),
        })
    except Exception as exc:  # one bad business must not kill a 2-hour batch
        row.update(
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc()[-2000:],
            wall_clock_s=round(time.time() - started, 2),
        )
    return row


# ── phase selection ──────────────────────────────────────────────────────────

def businesses_from_sample(sample: dict) -> list[dict]:
    out = []
    for stratum in sample.get("strata", []):
        for b in stratum.get("businesses", []):
            out.append({**b, "stratum": stratum.get("stratum")})
    return out


def phase_b_targets(out_dir: str, all_businesses: list[dict]) -> list[dict]:
    """Only businesses where Phase A recorded a would-be retry."""
    phase_a = load_checkpoint(out_dir, "A")
    if not phase_a:
        print("No Phase A checkpoint found — run --phase A first.")
        return []
    by_id = {b["business_id"]: b for b in all_businesses}
    targets = []
    for bid, row in phase_a.items():
        if row.get("status") != "ok":
            continue
        if row.get("would_retry_stages"):
            b = by_id.get(bid)
            if b:
                targets.append(b)
    return targets


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--phase", choices=["A", "B"], required=True)
    ap.add_argument("--sample", default="out_study/sample.json")
    ap.add_argument("--out", default="out_study")
    ap.add_argument("--sample-size", type=int, default=None,
                    help=f"Reviews per business (default: loader cap {loader.MAX_REVIEWS}).")
    ap.add_argument("--limit", type=int, default=None, help="Stop after N businesses (smoke test).")
    ap.add_argument("--sleep", type=float, default=0.0,
                    help="Seconds to pause between businesses (rate-limit relief).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Resolve and load reviews but make no LLM calls.")
    ap.add_argument("--allow-cap", action="store_true",
                    help="Proceed even when the review cap truncates a stratum.")
    args = ap.parse_args()

    if not os.path.exists(args.sample):
        print(f"Sample not found: {args.sample}\nRun scripts/sample_businesses.py first.")
        return 1
    with open(args.sample, encoding="utf-8") as fh:
        sample = json.load(fh)

    if not args.dry_run and not llm_config.is_configured():
        print(llm_config.NOT_CONFIGURED_MESSAGE)
        return 1

    all_businesses = businesses_from_sample(sample)

    # Refuse to run a silently-truncated study. loader.MAX_REVIEWS is read from
    # the environment at IMPORT time, so forgetting MAX_REVIEW_SAMPLE does not
    # raise -- it quietly clips every large business to the default 100 and
    # collapses the top strata into one indistinguishable band. That invalidates
    # the incidence-vs-review-count analysis with no visible error, which is the
    # worst possible failure mode for an unattended two-hour batch.
    effective_cap = args.sample_size or loader.MAX_REVIEWS
    biggest = max((b.get('review_count') or 0) for b in all_businesses)
    if biggest > effective_cap and not args.allow_cap:
        print('REFUSING TO RUN: the largest business in the sample holds '
              f'{biggest} reviews but the effective cap is {effective_cap}.')
        print(f'  Every business above {effective_cap} would be silently '
              'truncated, collapsing the top strata into one band.')
        print()
        print(f'  Fix:  MAX_REVIEW_SAMPLE={biggest} python scripts/run_study.py '
              f'--phase {args.phase}')
        print('  loader.MAX_REVIEWS is read at import, so it must be set in the')
        print('  environment -- passing --sample-size alone will not lift the cap.')
        print('  Override deliberately with --allow-cap if truncation is intended.')
        return 1
    targets = all_businesses if args.phase == "A" else phase_b_targets(args.out, all_businesses)
    if not targets:
        print("Nothing to run.")
        return 1

    done = load_checkpoint(args.out, args.phase)
    pending = [b for b in targets if b["business_id"] not in done]
    if args.limit:
        pending = pending[: args.limit]

    print(f"Phase {args.phase} ({PHASES[args.phase]}) — {len(targets)} target(s), "
          f"{len(done)} already done, {len(pending)} to run.")
    if args.dry_run:
        print("DRY RUN: no LLM calls, no checkpoint writes.\n")

    for i, b in enumerate(pending, start=1):
        label = f"[{i}/{len(pending)}] {b.get('stratum', '?')} {b['business_id']}"
        print(f"{label} {b.get('name', '')[:40]} ...", flush=True)
        row = run_one(b, args.phase, args.out, args.sample_size, args.dry_run)
        detail = row.get("error") or (
            f"{row.get('loaded_review_count', '?')} reviews, "
            f"{row.get('wall_clock_s', '?')}s, "
            f"would_retry={row.get('would_retry_stages') or '-'}"
        )
        print(f"    {row['status']}: {detail}", flush=True)
        if not args.dry_run:
            append_checkpoint(args.out, args.phase, row)
        if args.sleep and i < len(pending):
            time.sleep(args.sleep)

    print(f"\nPhase {args.phase} finished. Checkpoint: {_checkpoint_path(args.out, args.phase)}")
    if args.phase == "A" and not args.dry_run:
        rows = load_checkpoint(args.out, args.phase).values()
        ok = [r for r in rows if r.get("status") == "ok"]
        flagged = [r for r in ok if r.get("would_retry_stages")]
        print(f"  {len(ok)} completed, {len(flagged)} with a would-be retry "
              f"-> Phase B will run {len(flagged)} business(es).")
    return 0


# ── KNOWN GAP ────────────────────────────────────────────────────────────────
# Paper Table 8 (token and latency overhead) needs per-run token counts. Wall
# clock is recorded here; TOKENS ARE NOT, because nothing in app/ currently
# captures usage metadata from the provider. Closing this needs a small change
# in the agent base class to accumulate response usage into pipeline state —
# a fifth build item that was not in the original plan.

if __name__ == "__main__":
    sys.exit(main())
