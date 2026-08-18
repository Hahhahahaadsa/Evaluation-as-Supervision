"""Repetition-study tally: per-run defect probability, conditional on a defect
having been observed once in Phase A.

For each business the Phase A run recorded a specific retry-triggering stage.
This reports, across K identical observe-mode repetitions, how often ANY defect
recurred and how often THAT stage's defect recurred -- the two numbers the
two-phase design implicitly assumed were 1.0.
"""
import glob
import json
import os
import re
from collections import defaultdict

FREQUENCY_TOLERANCE = 0.05
ROOT = "backend/out_study"


def defects(obs):
    """Defect classes present in one run, from `facts` rather than the verdict."""
    out = set()
    for o in obs:
        f, stage = o["facts"], o["stage"]
        if f.get("status_error"):
            out.add("infra:" + stage)
            continue
        if stage == "analysis_agent" and f.get("contradictions"):
            out.add("contradiction")
        elif stage == "reasoning_agent":
            for p in f.get("patterns") or []:
                if p.get("missing_evidence_ids"):
                    out.add("unresolvable_evidence")
                if p.get("misaligned_evidence_ids"):
                    out.add("misaligned_aspect")
                cl, rc = p.get("claimed_frequency"), p.get("recomputed_frequency")
                if cl is not None and rc is not None and abs(cl - rc) > FREQUENCY_TOLERANCE:
                    out.add("statistic_divergence")
        elif stage == "strategy_agent" and f.get("untraceable_issues"):
            out.add("untraceable_recommendation")
        elif stage == "report_agent":
            if (f.get("invented_root_causes") or f.get("invented_recommendations")):
                out.add("unsupported_report")
            if f.get("name_mismatch") or f.get("size_mismatch"):
                out.add("metadata_mismatch")
    return out


phase_a = {x["business_id"]: x for x in
           map(json.loads, open(f"{ROOT}/A/checkpoint.jsonl", encoding="utf-8"))}

reps = defaultdict(dict)  # business_id -> {rep_k: row}
for path in sorted(glob.glob(f"{ROOT}/R/rep*/A/checkpoint.jsonl")):
    k = int(re.search(r"rep(\d+)", path).group(1))
    for line in open(path, encoding="utf-8"):
        row = json.loads(line)
        if row.get("status") == "ok":
            reps[row["business_id"]][k] = row

print(f"{'business':28s} {'PhaseA defect':26s} {'runs':>4s} {'any':>5s} {'same':>5s}")
tot_runs = tot_any = tot_same = 0
for bid, byk in reps.items():
    a = phase_a[bid]
    a_def = defects(a["observations"]) - {d for d in defects(a["observations"])
                                          if d.startswith("infra:")}
    n = len(byk)
    any_hit = same_hit = 0
    per_run = []
    for k in sorted(byk):
        d = defects(byk[k]["observations"])
        d = {x for x in d if not x.startswith("infra:")}
        per_run.append(sorted(d) or ["-"])
        if d:
            any_hit += 1
        if d & a_def:
            same_hit += 1
    tot_runs += n
    tot_any += any_hit
    tot_same += same_hit
    print(f"{a['business_name'][:28]:28s} {','.join(sorted(a_def))[:26]:26s} "
          f"{n:4d} {any_hit:5d} {same_hit:5d}")
    for k, d in zip(sorted(byk), per_run):
        print(f"    rep{k}: {','.join(d)}")

print()
if tot_runs:
    print(f"across {tot_runs} repetitions: any defect {tot_any} "
          f"({100*tot_any/tot_runs:.0f}%), same defect as Phase A {tot_same} "
          f"({100*tot_same/tot_runs:.0f}%)")
print("\nwall-clock:", {bid: [round(r["wall_clock_s"]) for _, r in sorted(byk.items())]
                        for bid, byk in reps.items()})
