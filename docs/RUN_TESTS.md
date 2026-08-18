# Running and Verifying the Project

Run backend commands from `backend/` so `import app` resolves correctly.

## Setup

```powershell
cd backend
python -m venv venv
./venv/Scripts/Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill `.env` with a real key and the approved provider/model configuration
(cloud Gemini: `gemini-2.5-flash` primary / `gemini-3.5-flash` fallback). To run
the agents against a **local** LLM instead, copy `backend/.env.local.example`
(Ollama; no API key required) - see [LOCAL_LLM.md](LOCAL_LLM.md). The
provider/model actually used is recorded in each dump's `run_config`. Never
commit `.env`.

This machine also has a verified interpreter:

```powershell
C:\Users\ADMIN\anaconda3\envs\ml\python.exe
```

Portable project documentation should still prefer a project virtual
environment.

## Backend Tests

```powershell
# All tests. Live tests execute when a key is present.
python -m pytest

# Offline suite only.
python -m pytest -m "not integration"

# Live model tests only.
python -m pytest -m integration

# Full live graph with the fixed in-memory sample.
python -m pytest tests/test_e2e_pipeline.py -v -m integration

# Supervision rules only (simple hub): measure/decide against the real
# backend/out/ dumps plus synthetic edge cases. Offline, fast.
python -m pytest tests/test_supervision.py -v
```

Verified on 2026-07-17 (after the simple-hub orchestrator, Option B):

- 119 collected;
- 113 offline tests passed (includes 23 new `test_supervision.py` tests and
  the rewritten hub graph/routing tests);
- 6 live tests deselected (run only when a reachable provider is configured).

The live tests use the provider/model from `.env` (cloud Gemini or local
Ollama). Do not label them Gemini, GPT, Groq, or another provider without
recording the actual configuration used - the dump's `run_config` records it
exactly.

## Test Scope

| File | Scope | External model |
| --- | --- | --- |
| `test_unit.py` | preprocessing and fuzzy matching | No |
| `test_data_pipeline.py` | mocked flow, seeded raw/SQLite sampling, cap validation | No |
| `test_analysis_agent.py` | analysis and reasoning validation/retries | Mocked |
| `test_strategy_agent.py` | strategy behavior and retries | Mocked |
| `test_report_agent.py` | report behavior and retries | Mocked |
| `test_llm_config.py` | provider/model resolution: local (Ollama) vs cloud, placeholder key, run_config label | No |
| `test_api.py` | FastAPI report/SSE contracts and trusted metadata | No |
| `test_supervision.py` | hub measure/decide rules on real dumps + synthetic edge cases | No |
| `test_orchestrator*.py` | criticality, hub verdicts/routing, retry-with-feedback, chained failures | No |
| `test_graph.py` | hub graph wiring: happy path, retry, halt, gave-up-on-record | Mocked |
| `test_eval_tier1.py` | deterministic evaluator regressions | No |
| `test_integration.py` | live analysis and reasoning | Yes |
| `test_e2e_pipeline.py` | live full graph on six in-memory reviews | Yes |

Known coverage gaps:

- no real 5.34 GB raw-loader performance regression;
- no SQLite-builder or partial-DB test;
- no frontend component interaction, accessibility, or lint test;
- no CI workflow.

## Evaluation

From `backend/`:

```powershell
# Deterministic fixture.
python -m eval.tier1_checks eval/fixtures/sample_dump

# Offline degradation scenarios.
python -m eval.harness --skip-live

# Live reproducibility and latency/cost.
python -m eval.harness --name "McDonald's" --pick 1 --runs 3

# Build Tier 2 JSONL after human labeling.
python eval/gold/build_gold_jsonl.py eval/gold/tier2_gold_labeling_worksheet.xlsx
python -m eval.tier2_analysis --gold eval/gold/analysis_gold.jsonl

# Tier 3 against a real stage dump. JUDGE_MODEL must differ from OPENAI_MODEL.
python -m eval.tier3_judge out/
```

Verified on 2026-07-17:

- Tier 1 fixture: 16/16 passed.
- Degradation harness: 8/8 passed (rewritten for the simple hub — covers
  proceed, low-confidence warning, insufficient-data halt, majority-failure
  retry, fabricated-evidence retry, gave-up-on-record, and report halt).
- Tier 1 on a fresh live hub run (`out_hub/`, Groq llama-3.3-70b): 22/22.

The focused chained-failure test verifies production node recovery state without
making live model calls. The synthetic harness still does not prove live
provider behavior.

## Verifying a Live Hub Run

After any live pipeline run, three things prove the supervision worked
(docs/ORCHESTRATOR_SIMPLE_HUB.md):

```powershell
# 1. Run against the same business as the committed baseline and dump stages.
python run_pipeline.py --name "LOVE Grille" --pick 1 --dump-stages out_hub

# 2. Score the dump. Evidence ids, aspect grounding, and frequencies should
#    all pass — frequencies are recomputed in Python and overwritten by the
#    orchestrator, so a frequency failure here means a supervision bug.
python -m eval.tier1_checks out_hub

# 3. Inspect supervision provenance in the summary:
#    retry_counts (which stages needed re-runs), flags (low_confidence,
#    frequency_corrected, *:gave_up_after_retries), last_verdict.
Get-Content out_hub/_summary.json
```

On the SSE endpoint, each stage now emits a `verdict` event and
`stage_start`/`stage_end` carry an `attempt` number — a retried stage appears
twice with attempt 1 and 2. Frontend consumers must key timelines by
`(stage, attempt)`.

## Run the API

```powershell
uvicorn app.main:app --reload
```

Process-level check:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

`/health` does not check the dataset, DB, API key, or provider.

## Run the Pipeline

```powershell
# Interactive.
python run_pipeline.py

# Select a match non-interactively and dump stages.
python run_pipeline.py --name "McDonald's" --pick 1 --sample-size 100 --dump-stages out/
```

Without `backend/data/processed/yelp.db`, a run scans the 5.34 GB raw review
file. Build the DB before timing or demonstrating the pipeline:

```powershell
python scripts/build_db.py
```

## Frontend

```powershell
cd ../frontend
npm install
npm run dev
```

Production build:

```powershell
npm run build
```

Frontend HTTP/SSE client tests:

```powershell
npm test
```

Verified on 2026-07-14: 2 client tests and the production build passed. The
client suite covers search/report requests, SSE parsing, and connection errors;
it does not exercise React component interactions or accessibility.

## Interpretation Rules

- Offline test success proves code-path behavior, not live model quality.
- The E2E integration test proves model + graph wiring, not Yelp loading or API.
- The loader uses `RANDOM_SEED`; identical candidate IDs, cap, and seed must
  produce identical sampled IDs.
- Record provider, model, dataset path, business ID, cap, and stage dump for any
  reported live result.
