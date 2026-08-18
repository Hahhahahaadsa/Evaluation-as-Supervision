"""Retry-triggering recurrence, using the supervisor's own verdicts.

Only some defect classes reach a `retry` verdict: low-rate star/sentiment
contradictions fall below CONTRADICTION_MAX and statistic divergences are
resolved by overwrite, so both warn rather than retry. Counting `facts` alone
therefore overstates what Phase B could ever have observed.
"""
import glob
import json
import re
from collections import defaultdict

ROOT = "backend/out_study"

phase_a = {x["business_id"]: x for x in
           map(json.loads, open(f"{ROOT}/A/checkpoint.jsonl", encoding="utf-8"))}

reps = defaultdict(dict)
for path in sorted(glob.glob(f"{ROOT}/R/rep*/A/checkpoint.jsonl")):
    k = int(re.search(r"rep(\d+)", path).group(1))
    for line in open(path, encoding="utf-8"):
        row = json.loads(line)
        if row.get("status") == "ok":
            reps[row["business_id"]][k] = row


def retry_stages(row):
    """Stages whose verdict was `retry`, excluding provider-error retries."""
    out = set()
    for o in row["observations"]:
        if o["would_be_verdict"] == "retry" and not o["facts"].get("status_error"):
            out.add(o["stage"])
    return out


print(f"{'business':28s} {'PhaseA retry stage':26s} {'runs':>4s} {'any':>4s} {'same':>5s}")
tr = ta = ts = 0
for bid, byk in reps.items():
    a = phase_a[bid]
    a_stages = retry_stages(a)
    n = len(byk)
    anyh = sum(1 for k in byk if retry_stages(byk[k]))
    same = sum(1 for k in byk if retry_stages(byk[k]) & a_stages)
    tr += n
    ta += anyh
    ts += same
    print(f"{a['business_name'][:28]:28s} {','.join(sorted(a_stages)) or '(none/infra)':26s} "
          f"{n:4d} {anyh:4d} {same:5d}")
    for k in sorted(byk):
        print(f"    rep{k}: {','.join(sorted(retry_stages(byk[k]))) or '-'}")

print()
print(f"across {tr} repetitions: any retry-triggering defect {ta} ({100*ta/tr:.0f}%), "
      f"same stage as Phase A {ts} ({100*ts/tr:.0f}%)")

# What a 5-business enforce arm should expect to see, given that per-run rate.
p = ta / tr
print(f"\nexpected retries in a 5-business enforce arm at p={p:.2f}: {5*p:.1f}")
print("Phase B observed: 1")
