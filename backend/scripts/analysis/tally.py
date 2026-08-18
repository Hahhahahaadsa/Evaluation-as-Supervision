"""Phase A incidence tally, computed from `facts` rather than `would_be_verdict`.

decide() returns on the first rule that fires, so verdicts undercount whenever a
stage carries two defect classes at once. facts is the whole measurement.
"""
import json
from collections import defaultdict

FREQUENCY_TOLERANCE = 0.05

rows = [json.loads(l) for l in open("backend/out_study/A/checkpoint.jsonl", encoding="utf-8")]

CHECKS = [
    "Unresolvable evidence ID",
    "Misaligned aspect",
    "Statistic divergence",
    "Star/sentiment contradiction",
    "Untraceable recommendation",
    "Unsupported report content",
    "Metadata mismatch",
    "Low sample size",
]

affected = defaultdict(set)     # check -> {business_id}
instances = defaultdict(int)    # check -> count
infra = []                      # (business, stage) pairs lost to provider errors
per_business = {}               # business_id -> (review_count, grounding_instances)

for x in rows:
    bid = x["business_id"]
    n = x["loaded_review_count"]
    ground = 0

    for o in x["observations"]:
        f, stage = o["facts"], o["stage"]
        if f.get("status_error"):
            infra.append((x["business_name"], stage))
            continue

        if stage == "analysis_agent":
            c = len(f.get("contradictions") or [])
            if c:
                affected["Star/sentiment contradiction"].add(bid)
                instances["Star/sentiment contradiction"] += c
                ground += c

        elif stage == "reasoning_agent":
            for p in f.get("patterns") or []:
                m = len(p.get("missing_evidence_ids") or [])
                a = len(p.get("misaligned_evidence_ids") or [])
                if m:
                    affected["Unresolvable evidence ID"].add(bid)
                    instances["Unresolvable evidence ID"] += m
                    ground += m
                if a:
                    affected["Misaligned aspect"].add(bid)
                    instances["Misaligned aspect"] += a
                    ground += a
                cl, rc = p.get("claimed_frequency"), p.get("recomputed_frequency")
                if cl is not None and rc is not None and abs(cl - rc) > FREQUENCY_TOLERANCE:
                    affected["Statistic divergence"].add(bid)
                    instances["Statistic divergence"] += 1
                    ground += 1

        elif stage == "strategy_agent":
            u = len(f.get("untraceable_issues") or [])
            if u:
                affected["Untraceable recommendation"].add(bid)
                instances["Untraceable recommendation"] += u
                ground += u

        elif stage == "report_agent":
            inv = len(f.get("invented_root_causes") or []) + len(f.get("invented_recommendations") or [])
            if inv:
                affected["Unsupported report content"].add(bid)
                instances["Unsupported report content"] += inv
                ground += inv
            mm = int(bool(f.get("name_mismatch"))) + int(bool(f.get("size_mismatch")))
            if mm:
                affected["Metadata mismatch"].add(bid)
                instances["Metadata mismatch"] += mm
                ground += mm

    low = [fl for o in x["observations"] for fl in o["flags"] if fl.startswith("low_confidence")]
    if low:
        affected["Low sample size"].add(bid)
        instances["Low sample size"] += len(low)

    per_business[bid] = (n, ground, x["business_name"], x["stratum"])

N = len(rows)
print(f"Phase A: {N} businesses\n")
print(f"{'Check':30s} {'Bus':>4s} {'Inst':>5s} {'%runs':>7s}")
for c in CHECKS:
    b = len(affected[c])
    print(f"{c:30s} {b:4d} {instances[c]:5d} {100*b/N:6.0f}%")

any_ground = {b for c in CHECKS[:-1] for b in affected[c]}
any_all = {b for c in CHECKS for b in affected[c]}
gi = sum(instances[c] for c in CHECKS[:-1])
print(f"{'Any grounding defect':30s} {len(any_ground):4d} {gi:5d} {100*len(any_ground)/N:6.0f}%")
print(f"{'Any defect (incl. low-n)':30s} {len(any_all):4d} {gi+instances['Low sample size']:5d} "
      f"{100*len(any_all)/N:6.0f}%")

print(f"\ninfrastructure-lost stage observations: {len(infra)}")
for b, s in infra:
    print("   ", b, "|", s)

print("\ngrounding instances by business (Figure 2 input):")
for bid, (n, g, name, st) in sorted(per_business.items(), key=lambda kv: kv[1][0]):
    print(f"  {st:4s} n={n:4d}  grounding={g:3d}  {name[:34]}")

import statistics as S
by_stratum = defaultdict(list)
for n, g, name, st in per_business.values():
    by_stratum[st].append(g)
print("\nmean grounding instances per stratum:")
for st in ["p25", "p50", "p75", "p90"]:
    v = by_stratum[st]
    print(f"  {st}: mean={S.mean(v):.1f}  values={sorted(v)}")

print("\nwall-clock (observe arm):")
w = [x["wall_clock_s"] for x in rows]
print(f"  mean={S.mean(w):.1f}s  median={S.median(w):.1f}s  min={min(w):.1f}  max={max(w):.1f}")
print("  tokens recorded:", sum(1 for x in rows if x.get("total_tokens") is not None), "/", N)
