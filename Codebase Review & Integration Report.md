# Codebase Review & Integration Report

**Reviewer:** Automated review (Cowork)
**Date:** June 2026
**Scope:** Alignment of the repository with the project overview (`README.md`, `AGENTS.md`), integration of `Testing_Orchestrator/` into `backend/app`, and repair of broken backend components.

> **Historical report.** This document records the June 2026 integration work.
> It is not the current project-status source. Use
> [`docs/PROGRESS.md`](docs/PROGRESS.md) and
> [`PROJECT_AUDIT.md`](PROJECT_AUDIT.md) for the 2026-07-14 state.

---

## 1. Summary

The `backend/` and `frontend/` trees match the documented structure in `README.md`. The main problems were a stale duplicate orchestrator folder living outside `backend/app`, several truncated source files, and an interactive script that could not run under `pytest`. All issues below are resolved. The offline backend test suite now passes: **44 passed, 5 live-LLM integration tests deselected**.

Current verification has advanced to **67 offline tests passed and 6 live tests
deselected**. FastAPI report endpoints, the React dashboard, the pipeline
monitor, SQLite support, and evaluation tooling were added after this historical
review.

---

## 2. Findings & Resolutions

### 2.1 `Testing_Orchestrator/` was a stale duplicate holding the only working orchestrator

`Testing_Orchestrator/` mirrored `backend/app` (agents, core, tests) but contained the **only working** orchestrator code, while `backend/app/core/` held empty `# TODO` stubs.

**Resolution:** Merged the working `graph.py`, `orchestrator.py`, and `state.py` into `backend/app/core/`, fixed their imports from `orchestrator.*` to `app.core.*`, moved the orchestrator tests into `backend/tests/`, and deleted the folder (including its committed `venv/`). The newer concrete `base_agent.py` already in `backend` was kept; the old abstract copy was dropped.

### 2.2 `contracts.py` was truncated (root cause of multiple import failures)

`app/schemas/contracts.py` was cut off mid-class at `Recommendation.expected_impact:`, producing a syntax error that broke the analysis, reasoning, strategy, and report agent imports.

**Resolution:** Completed the `Recommendation` model and added `StrategyOutput`, `ReportGeneratorInput`, and `ReportOutput` schemas, aligned with `README.md` §11.

### 2.3 `strategy_agent.py` and `report_agent.py` were empty truncated stubs

**Resolution:** Implemented both with a deterministic mode (for offline runs and tests) and an LLM-backed mode using the configured primary/fallback models, plus the `_candidate_models`, `_completion_options`, and `_load_environment` helpers their test suites require.

### 2.4 Orchestrator required credentials just to import

`OrchestratorAgent.__init__` built the LLM client eagerly, so importing the graph failed whenever `OPENAI_API_KEY` was unset, breaking test collection.

**Resolution:** Made the LLM client lazy — it is constructed only when an actual recovery decision needs it. Also wired `OPENAI_BASE_URL` into the LangChain client so the orchestrator uses the same endpoint as the agents.

### 2.5 `test_data_pipeline.py` blocked on `input()`

The file was Member 2's interactive demo and could not run non-interactively under `pytest`.

**Resolution:** Refactored the flow into a `run_demo()` function guarded by `if __name__ == "__main__"`, and added two mocked `pytest` tests that stub the loader/preprocessor and feed inputs.

### 2.6 Stale `test_fuzzy_top_n`

The test asserted `top_n` caps results for an exact-match query, contradicting Member 2's documented rule that all score-100 branches are returned.

**Resolution:** Updated the test to exercise `top_n` with a non-exact (typo) query, per the documented design.

---

## 3. Configuration

> **Update (2026-07-14):** The approved configuration is now cloud **Gemini**
> (`gemini-2.5-flash` primary / `gemini-3.5-flash` fallback) via the
> OpenAI-compatible endpoint, with a supported **local Ollama** profile
> (`backend/.env.local.example`). Provider/model is resolved centrally in
> `app/core/llm_config.py` and recorded per run in the eval dump `run_config`.
> The Groq setup below is retained for historical context only. See
> `docs/DECISIONS.md` (2026-07-14) and `docs/LOCAL_LLM.md`.

A local `backend/.env` was created using the OpenAI-compatible Groq endpoint, matching the model defaults present in `base_agent.py` *at the time of this review* (the defaults are now Gemini - see the update note above):

| Variable | Value |
|---|---|
| `OPENAI_BASE_URL` | `https://api.groq.com/openai/v1` |
| `OPENAI_MODEL` | `llama-3.3-70b-versatile` |
| `OPENAI_FALLBACK_MODEL` | `llama-3.1-8b-instant` |

`.env` is covered by `.gitignore` and is not committed. The API key was shared in chat and should be rotated as a precaution.

---

## 4. Test Results

```
44 passed, 5 deselected   (pytest -m "not integration")
```

The 5 deselected tests make real LLM API calls and are marked `integration`, consistent with `pytest.ini`. They were not run here because the sandbox cannot reach external APIs; they should pass on a machine with valid credentials.

---

## 5. Outstanding / Recommended Follow-ups

- **Line endings:** `git status` reports nearly every file as modified due to a CRLF↔LF mismatch (not real content changes). Adding a `.gitattributes` with `* text=auto eol=lf` would normalize this and remove the phantom diffs.
- **Rotate the Groq API key**, since it was shared in chat.
- The `core/config.py` `Settings` model remains separate from the loader, which
  reads `MAX_REVIEW_SAMPLE` and `RANDOM_SEED` directly from the environment.

The sampling and chained-recovery P0 defects were fixed on 2026-07-14. Current
priorities are cross-record contract validation, provider/model drift (resolved 2026-07-14), trusted
report metadata, and the missing local SQLite index. See
[`PROJECT_AUDIT.md`](PROJECT_AUDIT.md).
