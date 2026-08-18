"""Independent-judge assessment: the study's only non-circular *quality* measure.

A separate model scores the observe-arm and enforce-arm reports for the same
business against a rubric that shares nothing with the supervisor's checks. The
supervisor enforces evidence resolution, aspect alignment, frequency
recomputation, traceability and metadata match; none of those appear below. The
rubric scores qualities a reader would care about and the supervisor never sees.

Three guards against the ways this measure usually goes wrong:

  blind          the judge is never told which arm produced which report;
  counterbalanced  arm-to-label assignment alternates across repetitions, so a
                 positional preference cannot masquerade as a quality delta;
  repeated       each pair is judged REPS times. The repetition sub-study showed
                 this pipeline's single-run output is a draw; a single judging
                 pass would inherit exactly that problem.

Usage (from backend/, venv active):
    python scripts/run_judge.py --reps 3
"""

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv  # noqa: E402
from openai import OpenAI  # noqa: E402

RUBRIC = """You are assessing the quality of automated restaurant-review analysis
reports. Score each report independently on four dimensions, 1-5 (5 is best):

  actionability  Are the recommendations concrete enough for an owner to act on
                 this week, or are they generic advice that would apply to any
                 restaurant?
  specificity    Does the report commit to particulars -- named aspects, ranked
                 problems, stated magnitudes -- or does it hedge in generalities?
  coherence      Do the findings, root causes and recommendations form one
                 consistent argument, each following from the last?
  restraint      Does the report stay within what a review analysis can support,
                 or does it assert causes, motives or outcomes it cannot know?

Then state which report is better overall, or "tie".

Respond with JSON only, no prose and no code fences:
{"report_1": {"actionability": n, "specificity": n, "coherence": n, "restraint": n},
 "report_2": {"actionability": n, "specificity": n, "coherence": n, "restraint": n},
 "better": "report_1" | "report_2" | "tie",
 "reason": "one sentence"}"""


def render(rep: dict) -> str:
    """Flatten a report to text, dropping fields that could leak the arm."""
    parts = [
        f"Business: {rep.get('business_name')}",
        f"Reviews analysed: {rep.get('sample_size')}",
        f"\nExecutive summary:\n{rep.get('executive_summary')}",
    ]
    for key in ("key_findings", "root_causes", "recommendations", "limitations"):
        vals = rep.get(key) or []
        if isinstance(vals, str):
            vals = [vals]
        if vals:
            label = key.replace("_", " ").capitalize()
            body = "\n".join(f"  - {v}" for v in vals)
            parts.append(f"\n{label}:\n{body}")
    return "\n".join(parts)


def parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text)


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", default="out_study")
    ap.add_argument("--model", default=os.getenv("JUDGE_MODEL", "gemini-2.5-pro"))
    ap.add_argument("--sleep", type=float, default=3.0)
    args = ap.parse_args()

    subject_model = os.getenv("OPENAI_MODEL", "?")
    if args.model == subject_model:
        print(f"REFUSING TO RUN: judge model ({args.model}) is the model under "
              f"test ({subject_model}). A model cannot be its own independent judge.")
        return 1

    b_dir = os.path.join(args.out, "B")
    bids = [d for d in sorted(os.listdir(b_dir))
            if os.path.isdir(os.path.join(b_dir, d))]
    if not bids:
        print("No Phase B outputs found.")
        return 1

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"],
                    base_url=os.environ["OPENAI_BASE_URL"])
    out_path = os.path.join(args.out, "judge", "results.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    done = set()
    if os.path.exists(out_path):
        for line in open(out_path, encoding="utf-8"):
            r = json.loads(line)
            done.add((r["business_id"], r["repetition"]))

    print(f"Judge: {args.model} (subject: {subject_model}) — "
          f"{len(bids)} business(es) x {args.reps} repetition(s)")

    for k in range(1, args.reps + 1):
        for idx, bid in enumerate(bids):
            if (bid, k) in done:
                continue
            try:
                a = json.load(open(os.path.join(args.out, "A", bid, "report.json"), encoding="utf-8"))
                b = json.load(open(os.path.join(args.out, "B", bid, "report.json"), encoding="utf-8"))
            except FileNotFoundError:
                print(f"  skip {bid}: missing a report dump")
                continue

            # A report that failed to generate is an outage, not a quality
            # signal. Scoring an empty errored report against a complete one
            # measures provider availability and would enter the results as a
            # spurious quality delta.
            if a.get("status") != "success" or b.get("status") != "success":
                print(f"  skip {bid}: report status observe={a.get('status')} "
                      f"enforce={b.get('status')} — pair excluded as infrastructure loss")
                continue

            # Counterbalance: alternate which arm is shown first.
            observe_first = (k + idx) % 2 == 0
            first, second = (a, b) if observe_first else (b, a)
            label = {"report_1": "observe" if observe_first else "enforce",
                     "report_2": "enforce" if observe_first else "observe"}

            prompt = (f"{RUBRIC}\n\n=== REPORT 1 ===\n{render(first)}\n\n"
                      f"=== REPORT 2 ===\n{render(second)}")
            try:
                resp = client.chat.completions.create(
                    model=args.model, temperature=0,
                    messages=[{"role": "user", "content": prompt}])
                verdict = parse(resp.choices[0].message.content)
            except Exception as exc:
                print(f"  [{k}] {bid}: FAILED {type(exc).__name__}: {str(exc)[:120]}")
                continue

            row = {"business_id": bid, "business_name": a.get("business_name"),
                   "repetition": k, "judge_model": args.model,
                   "label_map": label, "verdict": verdict,
                   "observe_first": observe_first}
            with open(out_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            better = verdict.get("better")
            name = (a.get("business_name") or bid)[:26]
            print(f"  [{k}] {name:26s} better={label.get(better, better)}")
            time.sleep(args.sleep)

    print(f"\nDone. Results: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
