# AGENTS.md

This file tells Codex and Claude and team members how to work inside this repository.
Read this before changing the project structure or implementation plan.

## Communication

- Talk straight, no filler.
- If something is unknown, say it is unknown.
- Ask questions only when a decision is blocked or risky.

## Project Summary

- Course: COS30018 Intelligent Systems.
- Project: Multi-Agent System for Restaurant Review Analysis.
- Domain: F&B / restaurant review analysis.
- Goal: turn a random sample of restaurant reviews into patterns, root causes,
  recommendations, and a final web report.

## Current Project Decisions

These decisions are already agreed for the current plan:

- Use `gemini-2.5-flash` as the primary model for LLM-powered agents,
  reached through Gemini's OpenAI-compatible endpoint.
- Use `gemini-3.5-flash` as the fallback model when the primary is unavailable.
- This approved configuration is recorded per run in the evaluation dump
  (`_summary.json -> run_config`). See docs/DECISIONS.md (2026-07-14).
- The agents are provider-agnostic (OpenAI-compatible endpoint chosen by env),
  so the same code also runs on a **local** LLM via Ollama
  (`backend/.env.local.example`), satisfying the local-and-cloud requirement.
  See docs/LOCAL_LLM.md.
- Randomly sample up to 100 review records per selected restaurant.
- Do not claim that the system analyses every review in the Yelp dataset.
- Agent self-correction retry limit is 2.
- Keep documented sections for:
  - future user-flow diagram
  - evaluation plan
  - dataset implementation plan
  - Orchestrator state schema
  - error schema
  - report output schema
  - exact agent input/output contracts

## Repository Structure

- `backend/`: FastAPI, data loading, schemas, and agent pipeline.
- `backend/app/agents/`: Orchestrator, analysis, reasoning, strategic, and report agents.
- `backend/app/data/`: Yelp dataset loading, preprocessing, matching, and sampling.
- `backend/app/schemas/`: shared Pydantic contracts.
- `backend/data/raw/`: local raw dataset files. Do not commit real dataset files.
- `backend/data/processed/`: local generated dataset outputs. Do not commit generated data.
- `backend/eval/`: deterministic, labeled, and rubric-based evaluation tools.
- `frontend/`: Vite/React dashboard and pipeline monitor.
- `PROJECT_AUDIT.md`: verified strengths, weaknesses, and repair priorities.

## Backend Rules

- Keep the backend Python-first.
- Use FastAPI for HTTP endpoints.
- Use LangGraph for the multi-agent pipeline.
- Use Pydantic models for contracts instead of loose dictionaries where practical.
- Keep data loading separate from agent logic.
- Keep fuzzy restaurant matching separate from review sampling.
- The sample size cap must stay configurable, but the default is 100.

## Frontend Rules

- Keep the frontend simple until the backend pipeline works.
- Do not overbuild the UI before the report schema is stable.
- The frontend should call backend APIs; it should not read dataset files directly.

## Documentation Rules

- Keep `README.md`, `docs/PROGRESS.md`, `docs/DECISIONS.md`, and
  `docs/RUN_TESTS.md` consistent with the implemented code.
- Distinguish agreed target behavior from current implementation behavior.
- Describe review selection as seeded random sampling only while the loader and
  request cap continue to enforce that behavior.
- Record unresolved implementation deviations in `PROJECT_AUDIT.md`.

## Data Rules

- Do not commit `.env` files.
- Do not commit raw Yelp dataset files.
- Do not commit generated SQLite, Parquet, CSV, or JSONL data files.
- Use `.env.example` for required configuration names.

## Agent Contract Rules

- Every LLM-powered agent must return a structured JSON-compatible output.
- Every agent output must include:
  - `status`
  - `error_detail`
- If an agent fails validation, retry self-correction at most 2 times.
- After 2 failed retries, return `status: "error"` and let the Orchestrator decide
  whether to retry, skip, or halt.

## Git Rules

- Do not commit or push unless the user asks.
- Before committing, check `git status --short`.
- Stage only files related to the requested task.
- Do not rewrite history or reset the repo unless explicitly asked.

## Imported Claude Cowork project instructions

Follow my project plan COS30018 - Option D - Restaurants.pdf
