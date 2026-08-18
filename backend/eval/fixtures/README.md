# Evaluation Fixtures

`sample_dump/` is a committed `--dump-stages`-shaped output for offline or
future CI Tier 1 checks. It requires no LLM or API key. No CI workflow currently
exists.

## Provenance

The fixture was built deterministically, not from a live pipeline:

- `analysis.json` and `reasoning.json`: hand-authored 12-review data for
  "Example Bistro"; frequencies and evidence IDs were computed from the authored
  analyses.
- `strategy.json` and `report.json`: produced by the real deterministic
  `use_llm=False` agent paths.

This makes the fixture stable and appropriate for regression checks.

`tests/test_eval_tier1.py` runs the evaluator against this fixture and also
corrupts copies to verify that hallucinated evidence, incorrect frequencies,
fabricated report content, invalid enums, and bad completion status are caught.

Verified 2026-07-14: 16/16 Tier 1 checks passed.

## Limits

The fixture proves evaluator behavior and internal consistency. It does not
prove:

- live model quality;
- random sampling;
- Yelp raw-loader behavior;
- FastAPI or frontend behavior;
- production recovery-state propagation.

Keep fixtures small, synthetic, and free of sensitive content.
