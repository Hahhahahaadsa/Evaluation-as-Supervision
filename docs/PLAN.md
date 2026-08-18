# PLAN.md

Work plan for Phase 2 (close-out, due 17/06) and Phase 3 (due 30/06). Lanes are
split by workstream to minimise file collisions. See [`PROGRESS.md`](PROGRESS.md)
for live status and [`DECISIONS.md`](DECISIONS.md) for the rationale.

## Outstanding work

### Phase 2 - close-out (by 17/06), critical path

| # | Task |
| --- | --- |
| P2-1 | Wire `run_pipeline()` into `main.py` `/api/reports` (request/response models, async). Blocks the frontend. |
| P2-2 | Harden `orchestrator.decide_recovery` - wrap the recovery LLM call in try/except with a `halt` fallback (a provider 429 there currently crashes the graph). |
| P2-3 | Failure-injection tests: feed malformed agent outputs and assert the retry / skip / halt paths. |
| P2-4 | Replace the leaked-looking key in `backend/.env.example` with a placeholder; rotate any exposed key. |
| P2-5 | Finalise the report output schema (README 11.9 is still a draft). Cross-cutting: report agent, API response, and frontend all bind to it. |

### Phase 3 (by 30/06)

| # | Task |
| --- | --- |
| P3-1 | Dataset index keyed on `business_id` to replace the 5.3 GB linear scan, plus a reproducible sample seed. |
| P3-2 | Bind `Dashboard.jsx` to `/api/reports`; render the report sections; add top-3 match-confirmation UI. |
| P3-3 | Tier-1 deterministic evaluator (`backend/eval/`) consuming `--dump-stages`, plus latency / cost logging. |
| P3-4 | Tier-2 gold set (30-50 labelled reviews) for sentiment accuracy and aspect F1; Tier-3 report rubric. |
| P3-5 | Report polish, recovery strategies tested end to end, final demo prep. |
| P3-6 | Academic writeup: README 14 eval plan, decision log, final report doc. |

## Lane ownership

| Member | Lane | Owns | Phase 2 | Phase 3 |
| --- | --- | --- | --- | --- |
| Member 1 (you) | Evaluation & quality | `backend/eval/`, failure tests | P2-3 | P3-3, P3-4, README 14 |
| Member 2 | Optimize Run Time | note vào docs
| Member 4 | Frontend | `frontend/` | API client + match UI vs mocked schema | P3-2, report rendering |
| Member 3 | API wiring & orchestration & Database | `app/data/` | start P3-1 early | P3-1 |`app/main.py`, `app/core/orchestrator.py`, `pipeline.py`, `.env.example` | P2-1, P2-2, P2-4 | P3-5 (recovery) |

## Decisions affecting this plan

- Dataset index: SQLite is the default; a pre-extracted subset of demo
  restaurants is an acceptable shortcut if the demo is scripted to a few known
  restaurants - in which case Member 4 is under-loaded and should absorb P2-3 or
  pair on P2-1. See [`DECISIONS.md`](DECISIONS.md).
- Evaluation: three-tier plan (deterministic / gold set / rubric), README 14.
- Per-stage inspection: `run_pipeline.py --dump-stages <dir>` writes
  `analysis|reasoning|strategy|report.json` plus `_summary.json`.

## Sequencing and risks

1. Agree P2-5 (report schema) on day 1, as a team, before building against it -
   it unblocks the API response shape (M2), the frontend (M3), and the report
   agent. M2 records the agreed shape in `contracts.py`.
2. P2-1 (API) unblocks P3-2 (frontend binding); M3 mocks the response until then.
3. Member 2 owns the whole Phase 2 critical path (P2-1 + P2-2) - the bottleneck.
   P2-3 verifies P2-2, so M1 and M2 should pair on those.
4. M3 and M4 are light in Phase 2 - start Phase 3 early (M4 indexing is
   independent today; M3 builds against the mocked schema) to flatten the
   Phase 3 crunch.