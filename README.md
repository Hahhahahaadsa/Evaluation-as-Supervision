# COS30018 Intelligent Systems

## Multi-Agent System for Restaurant Review Analysis

This project turns a bounded set of Yelp restaurant reviews into sentiment and
aspect labels, recurring patterns, likely root causes, prioritised
recommendations, and a web report.

The loader now takes a reproducible seeded random sample of at most 100 reviews.
The cap is configurable and can be reduced per request.

## Current Status

| Area | Status |
| --- | --- |
| Data loading, matching, preprocessing | Working; SQLite or raw JSON fallback |
| Analysis, reasoning, strategy, report agents | Implemented |
| LangGraph orchestration | Implemented; chained-failure recovery regression passes |
| FastAPI | Working: health, business search, report, and SSE progress endpoints |
| React frontend | Working dashboard and pipeline monitor |
| Offline tests | 71 backend and 2 frontend passed on 2026-07-14 |
| Live integration tests | 6 collected; not rerun during the 2026-07-14 audit |
| Evaluation | All four tiers run live on the 73-review gold set; see [docs/EVALUATION_REPORT.md](docs/EVALUATION_REPORT.md) |
| Local SQLite index | Not built in the audited checkout |

## Repository Structure

```text
COS30018-IS/
|-- backend/
|   |-- app/
|   |   |-- agents/       # LLM agents and shared retry loop
|   |   |-- core/         # state, nodes, graph, orchestration, pipeline
|   |   |-- data/         # loading, fuzzy matching, preprocessing
|   |   |-- schemas/      # Pydantic contracts
|   |   `-- main.py       # FastAPI endpoints
|   |-- data/
|   |   |-- raw/          # local Yelp JSON; ignored by git
|   |   `-- processed/    # local SQLite/output files; ignored by git
|   |-- eval/             # Tier 1, Tier 1b, Tier 2, and Tier 3 evaluation
|   |-- scripts/build_db.py
|   |-- tests/
|   `-- run_pipeline.py
|-- frontend/
|   |-- src/api/
|   |-- src/components/
|   |-- src/pages/
|   |-- src/App.jsx
|   `-- src/styles.css
|-- docs/
|   |-- CLAUDE.md
|   |-- DECISIONS.md
|   |-- PROGRESS.md
|   `-- RUN_TESTS.md
|-- AGENTS.md
|-- PROJECT_AUDIT.md
|-- Codebase Review & Integration Report.md
`-- Member2 changes report.MD
```

Read [AGENTS.md](AGENTS.md) before changing architecture, data handling, agent
contracts, or the implementation plan.

## 1. Problem

Restaurant feedback is distributed across unstructured reviews. Owners need:

- recurring positive and negative patterns;
- evidence-linked operational issues;
- cautious root-cause hypotheses;
- prioritised actions rather than sentiment counts alone.

The system analyses only a bounded review set. It must never claim to analyse
every Yelp review.

## 2. Implemented User Flow

1. Search for a restaurant by name.
2. Review fuzzy matches and confirm a branch.
3. Load up to the configured review cap.
4. Clean review records.
5. Run analysis, reasoning, strategy, and report agents.
6. Return the report synchronously or stream stage progress through SSE.
7. Render the report in the React dashboard.

### Future user-flow diagram

Placeholder: add the final diagram after the team approves the final user flow.

## 3. Data Source and Selection

The project uses the Yelp Open Dataset:

- `backend/data/raw/yelp_academic_dataset_business.json`
- `backend/data/raw/yelp_academic_dataset_review.json`

The files are local and git-ignored.

### Implemented behavior

- `loader.search_business()` fuzzy-matches restaurants.
- `loader.load_reviews()` sorts candidates by review ID, then uses
  `RANDOM_SEED` for reproducible random selection.
- `MAX_REVIEW_SAMPLE` is validated from 1 to 100 and defaults to 100.
- POST and SSE report requests validate and apply an optional `sample_size`.
- Raw JSON and SQLite paths return the same IDs for the same data, seed, and cap.

### Dataset implementation plan

SQLite support, seeded sampling, and request-level cap handling are implemented.

## 4. SQLite Index

Build the index once from `backend/`:

```powershell
'python scripts/build_db.py'
```

Use `--rebuild` to replace an existing DB:

```powershell
python scripts/build_db.py --rebuild
```

The output is `backend/data/processed/yelp.db`. Without it, each report request
scans the 5.34 GB review file. The 2026-07-14 audit measured one raw lookup at
77.48 seconds.

Known limitation: the builder writes directly to the final DB path. An
interrupted build may leave a partial file that the loader treats as available.

## 5. Architecture

```text
Yelp data
  -> business matching
  -> review loading
  -> preprocessing
  -> Analysis Agent
  -> Reasoning Agent
  -> Strategy Agent
  -> Report Agent
  -> FastAPI
  -> React dashboard
```

The CLI, API, and live pipeline test reuse the production nodes in
`backend/app/core/nodes.py` through `backend/app/core/pipeline.py`.

## 6. Agent Roles

| Agent | Responsibility |
| --- | --- |
| Analysis | Sentiment and aspect labels for review batches |
| Reasoning | Recurring negative patterns and likely root causes |
| Strategy | Prioritised business recommendations |
| Report | Final structured report |
| Orchestrator | Retry, skip, or halt decisions after stage failure |

## 7. Models and Provider Configuration

**Approved configuration (single source of truth):**

- provider: Google Gemini via its OpenAI-compatible endpoint
  (`OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`);
- primary model: `gemini-2.5-flash`;
- fallback model: `gemini-3.5-flash`.

This is the configuration the code and `.env.example` default to, and it is
recorded per run in every evaluation dump (`_summary.json -> run_config`), so
results are always attributable to a known provider/model.

**Local profile (Ollama).** The Option-D requirement to run the agents on a
locally-deployed LLM is satisfied by a second profile
(`backend/.env.local.example`): Ollama's OpenAI-compatible endpoint on
`localhost:11434` with e.g. `llama3.1`. The provider is selected entirely by
environment variables - resolved centrally in
[`app/core/llm_config.py`](backend/app/core/llm_config.py) - so switching
between local and cloud is a `.env` change, not a code change, and no real API
key is needed for the local runtime. Full setup, run, and verification steps are
in [docs/LOCAL_LLM.md](docs/LOCAL_LLM.md).

The recorded `run_config` always reflects what actually ran
(`ollama-local (openai-compatible)` vs `google-gemini (openai-compatible)`), so
local and cloud evaluation results stay attributable. See
[docs/DECISIONS.md](docs/DECISIONS.md) (2026-07-14 entries) for the rationale
that superseded the earlier GPT-5.4 target and added the local profile.

## 8. Structured Contracts

The implemented contracts are in
`backend/app/schemas/contracts.py`. Every agent result includes `status` and
`error_detail`.

Implemented validation includes:

- sentiment and aspect enums;
- pattern frequency range 0-1;
- non-empty evidence ID lists;
- recommendation priority >= 1;
- structured strategy and report outputs.

### Exact agent input/output contracts

The Pydantic models are the executable source of truth. Pending hardening:

- require one analysis result per input review;
- preserve the exact input review-ID set;
- verify report `business_name` and `sample_size` against trusted state;
- enforce evidence and frequency grounding before returning an API response.

### Report output schema

`ReportOutput` contains:

- `title`
- `business_name`
- `sample_size`
- `executive_summary`
- `key_findings`
- `root_causes`
- `recommendations`
- `limitations`
- `status`
- `error_detail`

### Error schema

`AgentError` contains:

- `status`
- `agent`
- `error_type`
- `error_detail`
- `retry_count`
- `recoverable`

### Orchestrator state schema

`PipelineState` tracks business identity, review data, each agent output,
retry counts, skipped agents, errors, pipeline status, and the failed agent.

Each production node now records its current error and clears recovered state.
The handler inspects current outputs from the latest stage backward instead of
trusting a stale `failed_agent` value.

## 9. Error Handling

Agent-level behavior:

1. Call the configured model.
2. Parse JSON.
3. Validate with Pydantic.
4. Retry correction at most two times after schema failure.
5. Return a structured error after exhaustion.

Graph-level behavior:

- analysis and reasoning are critical;
- strategy and report may be skipped;
- the orchestrator chooses retry, skip, or halt;
- graph retries stop after two attempts;
- provider exceptions or invalid recovery responses deterministically retry
  while attempts remain, then halt critical stages or skip non-critical stages.

## 10. API

Run from `backend/`:

```powershell
uvicorn app.main:app --reload
```

Endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Process-level health |
| GET | `/api/businesses/search` | Fuzzy business search |
| POST | `/api/reports` | Synchronous full report |
| GET | `/api/reports/stream` | SSE progress and final report |

`/health` does not verify dataset, DB, credentials, or provider readiness.
The API has wildcard CORS and no authentication or rate limits, so it is a
local-demo API, not a safe public deployment.

## 11. Frontend

Run:

```powershell
cd frontend
npm install
npm run dev
```

Build:

```powershell
npm run build
```

Set `VITE_API_BASE_URL` when the backend is not at
`http://localhost:8000`.

Implemented views:

- Dashboard: business selection, KPIs, sentiment, aspects, findings, patterns,
  root causes, recommendations, and limitations.
- Pipeline Monitor: SSE stage status, timings, slowest-stage detection, and
  final summary.

Known UI gaps:

- Dashboard and Pipeline Monitor do not share report state;
- changing restaurant can leave a stale report visible;
- focus, live-region, and status accessibility need hardening.

## 12. Testing

From `backend/`:

```powershell
python -m pytest -m "not integration"
```

Verified on 2026-07-14:

- 77 backend tests collected;
- 71 offline backend tests passed;
- 6 live integration tests deselected;
- 2 frontend API-client tests passed;
- Tier 1 fixture passed 16/16 checks;
- degradation harness passed 6/6 synthetic scenarios;
- frontend production build passed.

The live E2E test uses four in-memory reviews. It validates real model and graph
wiring, not the raw Yelp path. Offline regressions now cover FastAPI POST/SSE and
the frontend HTTP/SSE client; real-dataset, component UI, and CI checks remain.

See [docs/RUN_TESTS.md](docs/RUN_TESTS.md).

## 13. Evaluation Plan and Status

### Tier 1: deterministic consistency

Implemented and offline:

- schema validity;
- evidence ID existence;
- aspect grounding;
- frequency recomputation;
- recommendation traceability;
- report subset checks;
- completion status.

### Tier 1b: pipeline behavior

Implemented:

- degradation paths;
- reproducibility interface;
- latency and token measurement.

The harness applies its requested seed and checks that repeated loads return the
same review-ID set. The raw and SQLite sampling regression runs offline.

### Tier 2: labeled analysis quality

Complete. The full 73-review LOVE Grille set was hand-labelled (starting from a
40-review stratified sample, then extended to all 73). Against those gold labels
the analysis agent scored sentiment accuracy 0.753 and aspect macro-F1 0.852.

### Tier 3: subjective usefulness

Run live with an independent, stronger judge model (`gemini-pro-latest`) to avoid
self-judging: root cause 4.8, recommendations 4.2, report 5.0 (1-5 scale).

All tier results ran against live `gemini-2.5-flash` output on 73 reviews; the
full write-up is in [docs/EVALUATION_REPORT.md](docs/EVALUATION_REPORT.md). No CI
workflow yet runs these checks automatically.

## 14. Milestones

| Phase | Status |
| --- | --- |
| Scope and contracts | Complete |
| Components and self-correction | Complete |
| Full pipeline and API wiring | Implemented; contract and API boundary regressions pass |
| Evaluation framework | Complete; all four tiers run live on the 73-review gold set |
| Demo readiness | Blocked by model-config, DB-index, and business-identity issues |

## 15. Priority Risks

| Priority | Risk | Required action |
| --- | --- | --- |
| Resolved P0 | Seeded random sampling and request cap | Raw/SQLite/API regression coverage passes |
| Resolved P0 | Chained recovery state | Current-agent and provider-fallback regressions pass |
| Resolved P1 | Schema-valid output may be incomplete or misidentified | Exact batch IDs/order and trusted report metadata regressions pass |
| Resolved P1 | API/frontend production boundaries lack tests | FastAPI POST/SSE and frontend HTTP/SSE client regressions pass |
| P1 | Business ID/name consistency and fuzzy acceptance remain weak | Add identity validation and an approved threshold |
| Resolved P1 | Provider/model sources disagreed | Approved config (gemini-2.5-flash primary / gemini-3.5-flash fallback) set everywhere and recorded in eval `run_config` |
| P1 | Missing local SQLite index causes minute-scale scans | Build and validate the index before demos |

## 16. Project Documentation

- [AGENTS.md](AGENTS.md): binding repository rules.
- [PROJECT_AUDIT.md](PROJECT_AUDIT.md): verified strengths, weaknesses, and
  repair order.
- [docs/PROGRESS.md](docs/PROGRESS.md): current implementation status.
- [docs/DECISIONS.md](docs/DECISIONS.md): append-only decision history.
- [docs/RUN_TESTS.md](docs/RUN_TESTS.md): commands and test scope.
- [docs/EVALUATION_REPORT.md](docs/EVALUATION_REPORT.md): four-tier live evaluation results.
- [backend/eval/README.md](backend/eval/README.md): evaluation usage.
- [Codebase Review & Integration Report.md](<Codebase Review & Integration Report.md>):
  historical integration work.
- [Member2 changes report.MD](<Member2 changes report.MD>): data-pipeline
  implementation notes.
