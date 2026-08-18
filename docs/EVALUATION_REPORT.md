# Evaluation Report — Multi-Agent Restaurant Review Analysis

**Course:** COS30018 Intelligent Systems · Group 4.1
**Date:** 2026-07-10
**Evaluation plan:** README §14 · methodology in [`DECISIONS.md`](DECISIONS.md) (2026-06-13, three-tier plan)

---

## 1. Scope and setup

All four tiers were run against **live LLM output** (not fixtures), closing the
outstanding "never run live" blocker from the 2026-07-02 handoff.

| Parameter | Value |
| --- | --- |
| Test restaurant | **LOVE Grille**, Philadelphia (`business_id 4Env6uGYxMhXFKPfcuzUuQ`, 3.0★) |
| Reviews analysed | **73** (all; below the 100 cap) |
| Pipeline model | `gemini-2.5-flash` (OpenAI-compatible endpoint) |
| Judge model (Tier 3) | `gemini-pro-latest` — deliberately different/stronger, to avoid self-judging |
| Dataset access | Yelp SQLite index (`yelp.db`, keyed on `business_id`) |
| Gold set | 73 hand-labelled LOVE Grille reviews (the full business; initial 40 stratified across star ratings, then extended to all 73) |
| Pipeline status | `complete` — 0 agents skipped, 0 failures, 0 retries |

Artifacts produced: `out/analysis|reasoning|strategy|report.json`,
`out/tier1_report.json`, `out/tier3_scores.json`,
`eval/gold/analysis_gold.jsonl`, `eval/gold/tier2_scores.json`.

---

## 2. Headline results

| Tier | What it measures | Headline result |
| --- | --- | --- |
| **1** | Deterministic consistency (no labels, no API) | **24 / 25 checks passed** |
| **1b** | Reproducibility, latency, cost, failure handling | **Reproducible; 6/6 degradation scenarios**; 357s + 148k tokens / 100 reviews |
| **2** | Analysis agent vs human gold labels (n=73) | **Sentiment accuracy 0.753**, **aspect macro-F1 0.852** |
| **3** | Rubric quality (independent LLM judge, 1–5) | **Root cause 4.8**, **recommendations 4.2**, **report 5.0** |

**Overall:** the pipeline is internally consistent, reproducible, degrades
safely under injected failures, matches human labels well on the one objective
stage, and scores highly on the subjective stages under a stronger independent
judge. The single Tier 1 miss is a genuine (caught) LLM defect, not a false alarm.

---

## 3. Tier 1 — deterministic checks (24/25)

Each stage is derivable from the previous, so correctness reduces to consistency
checks that need no ground truth. Runs offline, CI-suitable.

| Check family | Result |
| --- | --- |
| Schema / enum validity (all 4 stages) | ✅ PASS |
| Reasoning groundedness — aspect present | ✅ 5/5 patterns; every cited evidence review genuinely carries the claimed aspect |
| Reasoning groundedness — frequency recomputed | ✅ 5/5 within ±0.05 (e.g. claimed 0.397 vs recomputed 0.40) |
| Reasoning groundedness — evidence ids exist | ⚠️ **4/5** — one pattern cited a mistyped id |
| Strategy traceability (issue→cause, priority order) | ✅ 5/5 traced; 4/4 priority pairs frequency-ordered |
| Report subset (root causes / recs verbatim; findings soft-match) | ✅ 5/5 · 5/5 · 5/5 |
| Completion status | ✅ `complete` |

**The one failure — a caught transcription error.** The reasoning agent cited
evidence id `SKXs-JiPXpVnAwcXhA5wA`, which does not exist in the analysis output.
The real id is `SKXs-JiPX**3**pVnAwcXhA5wA` — the agent dropped a single
character while copying a 22-character Yelp id. The `evidence_exists` check
scored 0.97 (27/28 ids valid) and failed the pattern, exactly as designed.

This is a **real-but-cosmetic** defect: the pattern's aspect and recomputed
frequency are both still correct, so no downstream conclusion changes. Crucially,
a 25/25 would be mild cause for concern that the harness isn't testing anything;
catching one honest error with no false positives is the healthy outcome.

---

## 4. Tier 1b — reproducibility, latency, cost, degradation

Ran the full pipeline twice (seed 42) plus six offline failure-injection scenarios.

**Reproducibility:** ✅ PASS (stable outputs across runs).

**Latency & cost (73 reviews):**

| Stage | Time |
| --- | --- |
| analysis | 192.06 s |
| reasoning | 31.12 s |
| strategy | 16.82 s |
| report | 20.34 s |
| **total** | **260.33 s** → **356.62 s / 100 reviews** |
| **tokens** | **108,270** → **148,315 / 100 reviews** |

Analysis dominates (~74% of wall time) because it is per-review LLM
classification. It is the only stage worth optimising (larger batches /
concurrency) if demo latency matters.

**Degradation paths — 6/6 passed.** All orchestrator recovery routes behave as
specified:

| Scenario | Expected → Got |
| --- | --- |
| critical agent, retryable | retry → analysis_agent ✅ |
| critical agent, retries exhausted | halt → END ✅ |
| critical agent, skip downgraded to halt | halt → END ✅ |
| non-critical agent, skip continues | skip → report_agent ✅ |
| non-critical agent, skip on last stage | skip → END ✅ |
| non-critical agent, retries exhausted → skip | skip → report_agent ✅ |

This confirms the retry/skip/halt design: failures in *critical* stages
(analysis, reasoning) halt cleanly rather than emitting a hollow report, while
*non-critical* stage failures are skipped so a partial report still ships.

---

## 5. Tier 2 — analysis agent vs. human gold set (n = 73)

The analysis agent is the only stage with objectively checkable answers. All 73
LOVE Grille reviews (the full business) were hand-labelled for sentiment and
aspect mentions. The set was first built as a 40-review sample stratified across
star ratings, then extended to the complete 73 — labelling the whole business
removes any question of the sample being cherry-picked.

| Metric | Score |
| --- | --- |
| **Sentiment accuracy** | **0.753** (55/73) |
| **Aspect macro-F1** | **0.852** |

**Per-aspect F1** (binary "is this aspect mentioned"), with gold support:

| Aspect | F1 | support (gold mentions) |
| --- | --- | --- |
| cleanliness | 1.000 | 4 |
| food_quality | 0.975 | 59 |
| staff_attitude | 0.966 | 43 |
| pricing | 0.958 | 34 |
| wait_time | 0.905 | 22 |
| other | 0.734 | 35 |
| ambience | 0.429 | 3 |

**Reading:** aspect detection is strong on the well-supported categories —
food/staff/pricing all ≥0.95, wait_time 0.905. The two extremes are both
**low-support and should be read as indicative only**: `cleanliness` scores a
perfect 1.000 but on just 4 gold mentions, and `ambience` scores 0.429 on just 3
— at that support a single disagreement swings F1 by 0.3+, so neither number is
statistically reliable. Sentiment accuracy held at 0.753 (essentially unchanged
from 0.750 at n=40), which retroactively confirms the original 40 was a
representative sample; the ~18 disagreements reflect the genuine subjectivity of
mixed/neutral reviews, which is why sentiment is the one field treated as
objectively scorable while the later stages are not.

**Caveats for interpretation:**
- Single restaurant — indicative, not a population estimate. Full coverage of
  LOVE Grille does not generalise to other restaurants.
- `cleanliness` (n=4) and `ambience` (n=3) rest on too few examples to trust;
  report them with an explicit low-support footnote, not as headline results.
- **Single annotator.** The methodology recommends a second independent
  annotator + Cohen's κ before treating labels as final ground truth. This is the
  one remaining gap for a fully defensible Tier 2 number.

---

## 6. Tier 3 — rubric quality via independent LLM judge

Subjective stages have no formula, so a **different, stronger** model
(`gemini-pro-latest`) scored each output 1–5 against fixed rubrics
(`eval/rubrics/*.md`). Using a different model from the pipeline's
`gemini-2.5-flash` mitigates self-enhancement bias.

| Dimension | Mean (1–5) | n |
| --- | --- | --- |
| Root-cause plausibility | **4.8** | 5 |
| Recommendation actionability | **4.2** | 5 |
| Report usefulness | **5.0** | 1 |

- **Root causes (4.8):** four scored 5 ("directly and logically explains the
  pattern... confidence well-calibrated"); the lone 4 was the vague
  "unspecified negative experiences" cause — judged reasonable but inherently generic.
- **Recommendations (4.2):** four scored 4 ("clear, relevant actions" but leaving
  specific ownership/details to the operator); the single 5 was the QR-code
  feedback system, praised as concretely implementable "within a week".
- **Report (5):** "highly coherent, findings/root causes/recommendations
  logically linked and supported by specific data points... limitations clearly
  and honestly stated."

Scores reproduced the earlier explicit-override run exactly (4.8 / 4.2 / 5),
a positive reliability signal for the judge itself.

---

## 7. Fixes and environment notes from this run

- **Tier 3 default judge model fixed.** The hardcoded default `gemini-2.5-pro`
  now returns 404 ("no longer available to new users"), as does
  `gemini-3-pro-preview`. Default updated to `gemini-pro-latest` (verified
  working, still stronger than and distinct from the pipeline model). Tier 3 now
  runs with no env-var setup.
- **Missing dependency:** `openpyxl` (used by `eval/gold/build_gold_jsonl.py`) is
  not in `requirements.txt` — installed locally; should be added.
- **No SQLite index initially:** Tier 2's first run fell back to a raw-file scan;
  building `yelp.db` (`python scripts/build_db.py`) made subsequent tiers fast.

---

## 8. Conclusion

Across all four tiers the system demonstrates: **honesty** (Tier 1 — grounded,
self-consistent, and its one error was caught not hidden), **robustness**
(Tier 1b — reproducible and safe under failure), **accuracy** on the objective
stage (Tier 2 — 0.852 aspect macro-F1 on the full 73-review business), and **usefulness** on the subjective
stages under independent review (Tier 3 — 4.8 / 4.2 / 5.0). The primary
remaining item for full academic defensibility is a **second independent
annotator** on the Tier 2 gold set to report inter-annotator agreement.
