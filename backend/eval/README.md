# eval/ - Three-Tier Evaluation Harness

Implements the evaluation plan in [README section 14](../../README.md) and the
decision log in [docs/DECISIONS.md](../../docs/DECISIONS.md). All tiers consume
the per-stage JSON written by `run_pipeline.py --dump-stages <dir>`, so a
pipeline run and its scoring stay decoupled.

> **STATUS: implemented, last verified 2026-07-14.** All four modules are functional; the
> committed fixture (`fixtures/sample_dump/`) lets Tier 1 run fully offline.
> Outstanding: hand-label `gold/analysis_gold.jsonl` for Tier 2, and run Tier 1b
> / Tier 3 live against the approved provider (cloud Gemini or local Ollama - the
> resolved provider/model is recorded in each dump's `run_config`). Tier 1 passed 16/16 checks and
> the synthetic degradation harness passed 6/6 scenarios on 2026-07-14.

## Layout

| Path | Tier | Purpose |
|------|------|---------|
| `common.py` | - | Load a dump dir; `CheckResult`; scorecard printing. |
| `tier1_checks.py` | 1 | Deterministic checks (schema validity, reasoning groundedness, strategy traceability, report-subset, completion). No labels, no API. |
| `harness.py` | 1b | Runs the pipeline: reproducibility, latency & cost, degradation-path correctness. |
| `tier2_analysis.py` | 2 | Analysis-agent gold set: sentiment accuracy + per-aspect macro-F1 (scikit-learn). |
| `tier3_judge.py` | 3 | Rubric LLM-as-judge for subjective stages, using a **different** judge model. |
| `gold/tier2_gold_labeling_worksheet.xlsx` | 2 | 40-review human-labeling worksheet. |
| `gold/build_gold_jsonl.py` | 2 | Converts the completed worksheet to `analysis_gold.jsonl`. |
| `rubrics/*.md` | 3 | 1-5 rubrics for root-cause / recommendation / report. |
| `fixtures/` | 1 | Committed sample dump for offline or future CI checks. |

## Tier summary

- **Tier 1 (deterministic, no labels, CI-ready):** each stage is derivable from the
  previous, so correctness reduces to consistency checks - schema/enum validity,
  reasoning groundedness (evidence ids exist, aspect present, frequency matches
  within tolerance), strategy traceability, report-subset, completion rate.
- **Tier 2 (gold set, analysis only):** the one stage with objective answers.
  Hand-label 30-50 reviews; report sentiment accuracy + per-aspect macro-F1.
  Star rating is a noisy cross-check only.
- **Tier 3 (rubric LLM-judge):** subjective stages scored 1-5 against a rubric by
  a different/stronger judge model (mitigates self-enhancement bias). Small;
  informs the demo writeup, not CI.

No CI workflow currently exists. The checks are runnable locally and suitable
for a future workflow.

Tier 1b applies its requested seed to the loader and checks that repeated runs
return the same review-ID set. Offline tests also verify raw/SQLite parity.

## How to run

```bash
cd backend
# produce a dump
python run_pipeline.py --name "McDonald's" --pick 1 --dump-stages out/

python -m eval.tier1_checks out/                              # Tier 1
python -m eval.harness --name "McDonald's" --pick 1 --runs 3  # Tier 1b
python eval/gold/build_gold_jsonl.py eval/gold/tier2_gold_labeling_worksheet.xlsx
python -m eval.tier2_analysis --gold eval/gold/analysis_gold.jsonl   # Tier 2
$env:JUDGE_MODEL="<different-model>"
python -m eval.tier3_judge out/                              # Tier 3
```

## Remaining work

1. Human-label the Tier 2 worksheet, ideally with a second annotator.
2. Run latency/cost checks with the SQLite index and the approved provider
   (cloud or local; recorded in each dump's `run_config`).
3. Run Tier 3 against a real dump with an independent judge.
4. Add a CI workflow for Tier 1 and the offline test suite.

The synthetic degradation harness supplies complete failure metadata. A separate
offline regression now exercises chained failures through the production nodes;
live provider degradation remains unverified.
