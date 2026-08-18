# Project Progress

_Last verified: 2026-07-15._

## Snapshot

| Layer | Status | Notes |
| --- | --- | --- |
| Data loading and matching | Working with gaps | RapidFuzz and raw/SQLite paths work; no fuzzy threshold |
| Review selection | Working | Seeded random raw/SQLite sampling; request cap validated and applied |
| Preprocessing | Working | Cleans the five-column review contract |
| Analysis agent | Working | Batched outputs must match input review IDs and order |
| Reasoning agent | Working | Structured patterns and root causes |
| Strategy agent | Working | LLM and deterministic modes |
| Report agent | Working | Business/sample metadata is overwritten from validated input |
| LangGraph pipeline | Working | Chained-failure and recovery-provider regressions pass |
| FastAPI | Working | Health, search, report, and SSE endpoints; POST/SSE regressions pass |
| Frontend | Working with state/a11y gaps | Dashboard and Pipeline Monitor are API-bound; client tests pass |
| SQLite support | Implemented, not built locally | Raw fallback measured at 77.48 seconds |
| Evaluation | Complete | All four tiers run live: Tier 2 gold n=73, Tier 3 independent judge |
| Public deployment | Not ready | No auth, rate limiting, restricted CORS, or cost control |

## Verified Checks

- Python: 3.10.19.
- Backend dependencies: `pip check` passed.
- Backend collection: 77 tests.
- Offline backend suite: 71 passed.
- Live integration tests: 6 deselected.
- Frontend API-client suite: 2 passed.
- Tier 1 fixture: 16/16 checks passed.
- Synthetic degradation harness: 6/6 scenarios passed.
- Frontend: production build passed, 68.13 kB gzip JavaScript.
- Git: clean before the documentation task.

Live LLM tests were not rerun during the audit. The live E2E test uses an
in-memory sample; it does not validate the Yelp loader or FastAPI endpoint.

## Completed

- Data loading, preprocessing, business matching, and optional SQLite lookup.
- Seeded random sampling with a configurable cap and raw/SQLite parity.
- Analysis, reasoning, strategy, and report agents.
- Shared validation and two-attempt self-correction.
- LangGraph pipeline reused by CLI and API.
- Synchronous report and SSE progress endpoints.
- React dashboard, business picker, and pipeline monitor.
- Per-stage JSON dumps.
- Tier 1, Tier 1b, Tier 2 tooling, and Tier 3 rubric tooling.
- Offline evaluation fixture and regression tests.
- Current-agent recovery metadata, two graph retries, and deterministic
  provider-failure fallback.
- Exact analysis-batch ID/order validation with normal self-correction retries.
- Trusted report metadata plus FastAPI POST/SSE and frontend HTTP/SSE regressions.
- Provider-agnostic LLM layer: the same agents run on cloud (Gemini) or a local
  LLM (Ollama), selected by environment and recorded per run in `run_config`.

## Blocking Defects

1. ~~Binding model decision, code defaults, and example config differed.~~
   Resolved 2026-07-14: approved config (`gemini-2.5-flash` / `gemini-3.5-flash`)
   set everywhere, plus a local Ollama profile; the resolved provider/model is
   recorded per run in the eval dump `run_config`.
2. Local SQLite index is absent.
3. Fuzzy matching has no minimum acceptance threshold or ID/name consistency check.
4. Real-data, component UI, accessibility, and CI coverage remain incomplete.

Full evidence: [PROJECT_AUDIT.md](../PROJECT_AUDIT.md).

## Evaluation Status

All four tiers were run live against `gemini-2.5-flash` on the full 73-review
LOVE Grille set. Full write-up: [EVALUATION_REPORT.md](EVALUATION_REPORT.md).

| Tier | Status | Result |
| --- | --- | --- |
| Tier 1 deterministic | Run live | 24/25 checks passed (one caught, cosmetic evidence-id typo) |
| Tier 1b degradation | Run live | 6/6 injected-failure scenarios handled |
| Tier 1b reproducibility | Run live | Reproducible across seed-42 runs |
| Tier 1b latency/cost | Run live | 357s + 148k tokens / 100 reviews |
| Tier 2 gold labels | Complete | 73 hand-labelled reviews; sentiment acc 0.753, aspect macro-F1 0.852 |
| Tier 3 rubric judge | Run live | Independent judge (`gemini-pro-latest`): root cause 4.8, recs 4.2, report 5.0 |

Remaining evaluation follow-ups: add a CI workflow around Tier 1 and, if budget
permits, a second Tier 2 annotator.

## Next Work Order

1. ~~Align model/provider configuration.~~ Done - approved config
   (gemini-2.5-flash / gemini-3.5-flash) set everywhere and recorded per run.
2. Build and validate SQLite atomically.
3. Add business identity/match validation.
4. Add real-data, component UI, accessibility, and CI checks.
5. ~~Complete human and live evaluation.~~ Done - all four tiers run live on the
   full 73-review gold set (see EVALUATION_REPORT.md); CI workflow still to add.

## Demo Gate

Demo readiness requires:

- valid SQLite index;
- recorded provider/model (done - eval dump `run_config`, cloud or local);
- one real dataset -> API -> frontend run;
- Tier 1 pass on the resulting live dump.
