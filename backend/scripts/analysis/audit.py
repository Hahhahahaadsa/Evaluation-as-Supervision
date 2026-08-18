"""Self-audit: check the paper's claims against the data that produced them."""
import glob
import json
import re
import statistics as S
from collections import defaultdict

ROOT = "backend/out_study"
A = [json.loads(l) for l in open(f"{ROOT}/A/checkpoint.jsonl", encoding="utf-8")]
B = [json.loads(l) for l in open(f"{ROOT}/B/checkpoint.jsonl", encoding="utf-8")]

reps = defaultdict(dict)
for p in sorted(glob.glob(f"{ROOT}/R/rep*/A/checkpoint.jsonl")):
    k = int(re.search(r"rep(\d+)", p).group(1))
    for line in open(p, encoding="utf-8"):
        r = json.loads(line)
        if r.get("status") == "ok":
            reps[r["business_id"]][k] = r

print("=== 1. was input actually identical across runs? ===")
for x in A:
    if x["loaded_review_count"] != x["expected_review_count"]:
        print("  MISMATCH", x["business_name"])
byb = defaultdict(set)
for bid, byk in reps.items():
    for k, r in byk.items():
        byb[bid].add(r["loaded_review_count"])
print("  per-business distinct loaded counts across reps:",
      {k[:8]: sorted(v) for k, v in byb.items()})
print("  (cap 214 >= every business, so selection loaded ALL reviews: no sampling)")

print("\n=== 2. latency: enforce vs the 25 observe repetitions ===")
obs_mean = {}
for bid, byk in reps.items():
    w = [r["wall_clock_s"] for r in byk.values()]
    obs_mean[bid] = S.mean(w)
    print(f"  {byk[1]['business_name'][:26]:26s} observe mean={S.mean(w):7.1f} "
          f"sd={S.pstdev(w):6.1f} range={min(w):.0f}-{max(w):.0f}")
bmap = {x["business_id"]: x["wall_clock_s"] for x in B}
om = S.mean([obs_mean[b] for b in obs_mean])
em = S.mean([bmap[b] for b in obs_mean])
print(f"  observe mean over 25 runs = {om:.1f}s ; enforce mean over 5 = {em:.1f}s "
      f"-> {100*(em-om)/om:+.1f}%")
spread = S.mean([S.pstdev([r['wall_clock_s'] for r in byk.values()]) / S.mean([r['wall_clock_s'] for r in byk.values()])
                 for byk in reps.values()])
print(f"  mean within-business coefficient of variation across repeats: {100*spread:.1f}%")
print("  -> a 5-run comparison cannot resolve an effect smaller than this.")

print("\n=== 3. did Phase A report zero for classes that DO occur? ===")


def classes(row):
    out = set()
    for o in row["observations"]:
        f, s = o["facts"], o["stage"]
        if f.get("status_error"):
            continue
        if s == "reasoning_agent":
            for p_ in f.get("patterns") or []:
                if p_.get("missing_evidence_ids"):
                    out.add("unresolvable_evidence")
                if p_.get("misaligned_evidence_ids"):
                    out.add("misaligned_aspect")
        if s == "report_agent" and (f.get("invented_root_causes") or f.get("invented_recommendations")):
            out.add("unsupported_report")
        if s == "report_agent" and (f.get("name_mismatch") or f.get("size_mismatch")):
            out.add("metadata_mismatch")
    return out


a_seen = set().union(*(classes(x) for x in A))
r_seen = set().union(*(classes(r) for byk in reps.values() for r in byk.values()))
print("  Phase A (20 runs) saw:", sorted(a_seen) or "none of these")
print("  repetitions (25 runs) saw:", sorted(r_seen) or "none")
print("  reported as ZERO in Phase A but observed in repetitions:",
      sorted(r_seen - a_seen) or "none")

print("\n=== 4. Figure 2: how stable is a single draw per business? ===")
for bid, byk in reps.items():
    name = byk[1]["business_name"][:26]
    per = []
    for k in sorted(byk):
        g = 0
        for o in byk[k]["observations"]:
            f, s = o["facts"], o["stage"]
            if f.get("status_error"):
                continue
            if s == "analysis_agent":
                g += len(f.get("contradictions") or [])
            elif s == "reasoning_agent":
                for p_ in f.get("patterns") or []:
                    g += len(p_.get("missing_evidence_ids") or [])
                    g += len(p_.get("misaligned_evidence_ids") or [])
                    cl, rc = p_.get("claimed_frequency"), p_.get("recomputed_frequency")
                    if cl is not None and rc is not None and abs(cl - rc) > 0.05:
                        g += 1
            elif s == "strategy_agent":
                g += len(f.get("untraceable_issues") or [])
            elif s == "report_agent":
                g += len(f.get("invented_root_causes") or []) + len(f.get("invented_recommendations") or [])
        per.append(g)
    pa = [x for x in A if x["business_id"] == bid][0]
    print(f"  {name:26s} PhaseA draw was ... reps={per} mean={S.mean(per):.1f} range={min(per)}-{max(per)}")
