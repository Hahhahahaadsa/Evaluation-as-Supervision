# CLAUDE.md

Guidance for Claude Code (and any AI agent) working in this repository.
Read [`AGENTS.md`](../AGENTS.md) first — it holds the binding project rules. This
file adds the practical "how to work here" details.

## What this project is

Multi-agent system (COS30018 Intelligent Systems) that turns a sample of Yelp
restaurant reviews into patterns, root causes, recommendations, and a final web
report. Backend is Python (FastAPI + LangGraph); frontend is a Vite/React
placeholder.

See [`PROGRESS.md`](PROGRESS.md) for current status, [`DECISIONS.md`](DECISIONS.md)
for the decision log, and [`RUN_TESTS.md`](RUN_TESTS.md) for running tests, and [`PLAN.md`](PLAN.md) for the Phase 2 / 3 work plan.

## Repository layout (high level)

- `backend/app/agents/` — analysis, reasoning, strategy, report agents (`base_agent.py` holds the shared LLM + self-correction loop).
- `backend/app/core/` — `state.py` (PipelineState), `graph.py` (LangGraph wiring), `orchestrator.py` (retry/skip/halt), `config.py`.
- `backend/app/data/` — `loader.py`, `matching.py` (fuzzy), `preprocessor.py`.
- `backend/app/schemas/contracts.py` — Pydantic contracts shared by every stage.
- `backend/tests/` — unit + integration + e2e tests.
- `frontend/` — Vite/React dashboard placeholder.

The full file tree lives in [`README.md`](../README.md#repository-structure).

## Environment & commands

- **Always run backend commands from the `backend/` directory.** Paths and pytest config assume `cwd = backend/`.
- Use the project virtualenv: `backend/venv/`. The system Python does **not** have the deps (`pytest`, `langgraph`, `openai`, …).
  - PowerShell: `./venv/Scripts/Activate.ps1`
  - Direct interpreter: `./venv/Scripts/python.exe -m pytest`
- Install deps: `pip install -r requirements.txt` (from `backend/`).
- Run the API (stub today): `uvicorn app.main:app --reload`.
- Data demo (interactive, real dataset): `python -m tests.test_data_pipeline`.
- Run the full pipeline on a real restaurant: `python run_pipeline.py --name "..." --pick 1`. Add `--dump-stages <dir>` to write each agent phase's JSON (input for the evaluator).

## Tests

Full detail in [`RUN_TESTS.md`](RUN_TESTS.md). Quick reference (from `backend/`):

```bash
python -m pytest                      # everything
python -m pytest -m "not integration" # fast unit suite, no LLM calls
python -m pytest -m integration       # real Gemini LLM calls (needs OPENAI_API_KEY)
```

Integration/e2e tests auto-skip when `OPENAI_API_KEY` is unset.

## Conventions

- Every agent returns a JSON-compatible dict with `status` and `error_detail`.
- Validate outputs against `app/schemas/contracts.py` (Pydantic) — don't pass loose dicts between stages.
- Agent self-correction retries at most 2 times; after that it returns `status: "error"` and the orchestrator decides retry/skip/halt.
- Critical agents are `analysis` and `reasoning` (see `OrchestratorAgent.CRITICAL_AGENTS`); strategy and report are non-critical and may be skipped.
- Keep data loading separate from agent logic; keep fuzzy matching separate from sampling.
- LLM-backed agents support a deterministic `use_llm=False` mode for offline/unit tests.

## Gotchas (learned the hard way)

- **Dataset paths**: `loader.py` anchors relative paths to the **repo root** (`Path(__file__).parents[3]`). So `.env` paths must be repo-root-relative, e.g. `backend/data/raw/yelp_academic_dataset_business.json`.
- **Dataset files** live at `backend/data/raw/*.json` as plain files (they were once wrapped in redundant same-named folders — flattened). They are git-ignored.
- **Real-LLM tests are non-deterministic**: don't assert the model echoes input fields verbatim, and expect occasional graceful degradation (a non-critical stage skipping). The e2e test retries the whole pipeline a few times to stay reliable.
- **Secret hygiene**: `backend/.env.example` historically contained a live-looking key. Never commit real keys; use placeholders.

## Git

Do not commit or push unless asked. Check `git status --short` first; stage only
task-related files. Never rewrite history unless explicitly told to.
