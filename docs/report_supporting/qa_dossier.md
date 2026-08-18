# QA Dossier — COS30018 Group 4.1 Multi-Agent Restaurant Review Analysis

Single source of truth for the report writer. Every claim is cross-checked against the actual code at the current `main` commit (`26f0dd8`). File paths are absolute-in-repo (relative to repo root `C:\Users\qdung\COS30018\COS30018_Group-4.1_Multi-Agent-System-for-Restaurant-Review-Analysis`). Line numbers are from the files as read on 2026-07-22.

> **HEADLINE FINDING (read first).** The repository has moved past what most of the docs describe. The **simple-hub orchestrator (Option B)** described in `docs/ORCHESTRATOR_SIMPLE_HUB.md` as *"Proposed alternative. Not yet agreed, not yet implemented"* **IS fully implemented and wired into the live graph** (commit `953a6bd`, files `backend/app/core/graph.py`, `supervision.py`, `orchestrator.py`). Consequently many older docs (README §5/§6/§9, PROJECT_AUDIT, PROGRESS, FINDINGS_2026-07-16 F7, EVALUATION_REPORT) describe the *old* linear/error-handler design and stale test/eval counts. See DISCREPANCIES.

---

## 1. VERIFIED FACTS

### 1.1 System architecture — agents and orchestration

- **Four LLM agents + an orchestrator.** Agent files: `backend/app/agents/analysis_agent.py`, `reasoning_agent.py`, `strategy_agent.py`, `report_agent.py`. Orchestrator: `backend/app/core/orchestrator.py`. (README §6 table lists Analysis, Reasoning, Strategy, Report, Orchestrator.)
- **Shared base class** `BaseAgent` in `backend/app/agents/base_agent.py:45` centralises: OpenAI-compatible client construction (`base_agent.py:58`), JSON response mode (`response_format={"type":"json_object"}`, `base_agent.py:84`), Pydantic validation + correction retries (`_run_with_retry`, `base_agent.py:101-144`), fallback-model call (`_call_llm`, `base_agent.py:77-99`), token accounting (`total_tokens_used`, `base_agent.py:51`, `_record_usage:71-75`), and retry-feedback injection (`_with_feedback`, `base_agent.py:62-69`).
- **Orchestration is the SIMPLE HUB (Option B), fully wired.** `backend/app/core/graph.py`:
  - Entry point is `preprocess` → `analysis_agent`; every agent then routes to a single `orchestrator` node (`graph.py:122-127`).
  - The orchestrator is the **only routing node** (`graph.py:129-135`, `route_from_orchestrator:97-106`).
  - Graph shape: `preprocess → analysis → ORCH → reasoning → ORCH → strategy → ORCH → report → ORCH → END` (`graph.py:7`). On retry, the orchestrator routes back to the same stage; on halt it routes to `END`.
  - The orchestrator runs **after every stage, every run** — not only on failure (`orchestrator.py:43-54`, `graph.py:38-91`).
  - `RECURSION_LIMIT = 50` (`graph.py:32`); callers MUST pass `{"recursion_limit": 50}` (`pipeline.py:78-81`, `main.py:228`). Worst case = 25 node visits = exactly LangGraph's default (`graph.py:30-31`).
- **Verdict vocabulary:** `proceed | proceed_with_warning | retry | halt` (`supervision.py:40`, `Decision` dataclass `supervision.py:38-42`). **`skip` was dropped** — a non-critical stage that exhausts retries becomes `proceed_with_warning` with a `<stage>:gave_up_after_retries` flag and is recorded in `skipped_agents` (`supervision.py:278-282`, `graph.py:75-82`).
- **Measuring is separate from deciding** (`supervision.py`): `measure(stage, state)` computes facts (pure Python, no LLM, `supervision.py:101-262`); `decide(stage, facts, retry_counts)` applies hard rules (`supervision.py:268-358`). No LLM is used on the common path.
- **Frequency is authoritative in Python (F2a implemented):** on a reasoning `proceed`, `apply_frequency_corrections()` overwrites the LLM's claimed `frequency` with the recomputed value (`graph.py:84-87`, `supervision.py:364-385`). Divergence beyond `FREQUENCY_TOLERANCE=0.05` raises a `frequency_corrected:<aspect>:<claimed>-><recomputed>` flag (`supervision.py:322-329`).
- **Retry-with-feedback loop:** the orchestrator writes `state["retry_feedback"]` (`graph.py:58`); each agent node consumes+clears it (`nodes.py:57-65`, `_consume_retry_feedback`) and passes it to the agent, which appends it to the prompt (`base_agent.py:62-69`, `_SUPERVISOR_FEEDBACK_PROMPT:37-42`). This is the fix for temperature-0 identical re-runs.
- **`OrchestratorAgent` still keeps the legacy `decide_recovery(failed_agent, error_detail, retry_count)` method** (`orchestrator.py:56-89`) with an LLM prompt fallback, but it is NOT on the live routing path — the graph calls `supervision.decide` via `orchestrator_node` (`graph.py:44-45`). `CRITICAL_AGENTS = {"analysis", "reasoning"}`, `MAX_RECOVERY_RETRIES = 2` (`orchestrator.py:17-18`). LLM client is lazy (`orchestrator.py:20-34`).

### 1.2 Decision rules (exact thresholds — `supervision.py:26-35, 286-358`)

Module constants: `MIN_VIABLE_N = 5`, `LOW_CONFIDENCE_N = 30`, `CONTRADICTION_MAX = 0.20`, `FREQUENCY_TOLERANCE = 0.05`, `TRACE_SIMILARITY = 0.35`, `MAX_RECOVERY_RETRIES = 2`. `AGENT_SEQUENCE = ["analysis_agent","reasoning_agent","strategy_agent","report_agent"]`, `CRITICAL_STAGES = {"analysis_agent","reasoning_agent"}`.

- Analysis: `n_success < 5` → **halt** (`insufficient_data`); `failure_ratio > 0.5` → **retry**; `contradiction_rate > 0.20` → **retry**; `n_success < 30` → **proceed_with_warning** (`low_confidence:n=<n>`); else **proceed** (`supervision.py:287-302`).
- Reasoning: status error → retry; missing/misaligned evidence ids → **retry** (fabrication gate); frequency divergence > 0.05 → **proceed_with_warning**; else proceed (`supervision.py:304-330`).
- Strategy: status error → retry; untraceable recommendation issues (`< 0.35` similarity to any upstream cause/pattern) → **retry** (`supervision.py:332-339`).
- Report: status error → retry; invented root causes/recs, or `business_name`/`sample_size` mismatch vs trusted state → **retry** (`supervision.py:341-356`).
- Retry cap gates everything: `retry_counts[stage] >= 2` turns a would-be retry into **halt** (critical or report) or **proceed_with_warning** (non-critical) (`supervision.py:278-283`).

### 1.3 State schema (`backend/app/core/state.py`)

`PipelineState` (TypedDict) fields: `business_name`, `business_id`, `reviews_df` (pandas DataFrame), `analysis_results` (list[dict]), `reasoning_output`, `strategy_output`, `report_output`, `retry_counts` (dict[str,int]), `skipped_agents` (list), `errors` (dict[str,str]), `pipeline_status` (`"running" | "halted" | "complete"`, terminal semantics only — `state.py:23`), `failed_agent`, and three **hub fields**: `flags` (list, e.g. `"low_confidence:n=13"`), `retry_feedback` (str|None), `last_verdict` (str|None) (`state.py:26-29`).

### 1.4 Data pipeline

- **Dataset:** Yelp Open Dataset — `backend/data/raw/yelp_academic_dataset_business.json` and `..._review.json` (git-ignored; both present in this checkout). Review file ~5.34 GB (README §4).
- **SQLite index:** `backend/data/processed/yelp.db` built by `backend/scripts/build_db.py`. **The DB file is present in this checkout** (git status clean; file exists in `backend/data/processed/yelp.db`). Two tables: `businesses` (business_id PK, name, address, city, state, review_count — `build_db.py:36-45`) and `reviews` (review_id, business_id, stars, text, date — `build_db.py:79-87`) with `CREATE INDEX idx_reviews_business ON reviews(business_id)` (`build_db.py:117`).
- **Loader** `backend/app/data/loader.py`: `_db_available()` = `os.path.exists(DB_PATH)` (`loader.py:44-45`); prefers SQLite, falls back to raw-JSON line scan (`loader.py:139-169`). `MAX_REVIEWS` from `MAX_REVIEW_SAMPLE` env, **validated 1–100, default 100** — raises if out of range (`loader.py:30-33`). `RANDOM_SEED` default 42 (`loader.py:31`).
- **Sampling** `_sample_reviews` (`loader.py:102-113`): sorts candidates by `review_id` (order-independent), and **if `len(df) <= limit` returns everything with no sampling** (`loader.py:108-109`); otherwise `df.sample(n=limit, random_state=RANDOM_SEED)`. Raw and SQLite share this helper → parity.
- **Fuzzy matching** `backend/app/data/matching.py` (RapidFuzz, comments in Vietnamese): pre-filter by first character, fallback to full list if `<10` candidates (`matching.py:11-20`); `process.extract(..., scorer=fuzz.ratio, limit=50)` (`matching.py:24-29`); dedupe by business_id; sort by (score, review_count) desc. **If top score == 100, returns ALL score-100 rows** (not capped by `top_n`); else returns `top_n` (`matching.py:47-51`). **No minimum acceptance threshold.**
- **Preprocessor** `backend/app/data/preprocessor.py` (comments in Vietnamese): keeps 5 columns, drops rows missing review_id/business_id/text, `stars` cast to int and `clip(1,5)`, `date` → datetime, text stripped, drops empty text and duplicate review_ids (`preprocessor.py:12-28`).
- **Config duplication:** `backend/app/core/config.py` has a separate `Settings` (max_review_sample=100, random_seed=42) that is **not used by the loader** — the loader reads env directly (noted in Codebase Review §5).

### 1.5 Pydantic contracts (`backend/app/schemas/contracts.py`) — exact models and fields

- `AspectCategory` = Literal[`food_quality`, `staff_attitude`, `pricing`, `wait_time`, `ambience`, `cleanliness`, `other`] (`:6-14`).
- `ReviewRecord`: review_id, business_id, stars(int), text, date (`:17-22`).
- `AgentError`: status(="error"), agent, error_type, error_detail, retry_count(int), recoverable(bool) (`:25-31`).
- `AspectLabel`: category(AspectCategory), label(Literal positive/negative/neutral) (`:34-36`).
- `AnalysisOutput`: review_id, sentiment(Literal positive/negative/neutral/**mixed**), aspects(list[AspectLabel]), status(Literal success/error), error_detail(str|None) (`:39-44`). **Retains no `stars`/`date`/`text`** (F13a/F3).
- `AnalysisBatchOutput`: analyses(list[AnalysisOutput]) (`:47-50`).
- `Pattern`: description, aspect(AspectCategory), **frequency: float Field(ge=0.0, le=1.0)**, evidence_review_ids: list[str] Field(**min_length=1**) (`:53-57`).
- `RootCause`: pattern, cause, confidence(Literal low/medium/high) (`:60-63`) — **no `evidence_review_ids`** (F5).
- `ReasoningOutput`: patterns(list[Pattern]), root_causes(list[RootCause]), status, error_detail (`:66-70`).
- `StrategicAgentInput`: patterns, root_causes (`:73-75`).
- `Recommendation`: **priority: int Field(ge=1)**, issue, action, category, expected_impact (`:78-83`).
- `StrategyOutput`: recommendations(list[Recommendation]), status, error_detail (`:86-89`).
- `ReportGeneratorInput`: business_name, sample_size(ge=0), analysis_summary(dict), reasoning_summary(dict), recommendations (`:92-97`).
- `ReportOutput`: title(default "Restaurant Review Analysis Report"), business_name, sample_size(ge=0), executive_summary, key_findings, root_causes(list[RootCause]), recommendations, limitations, status, error_detail (`:100-110`).

### 1.6 Self-correction / retry mechanics

- **Max retries = 2** (three attempts total). `BaseAgent.MAX_RETRIES = 2` (`base_agent.py:46`); retry loop `for attempt in range(self.MAX_RETRIES + 1)` (`base_agent.py:115`).
- **Correction prompt** `_CORRECTION_PROMPT` (`base_agent.py:17-32`) matches CLAUDE.md §7.2 template exactly (original_task, invalid_output, validation_error, schema, "Return only valid JSON. Do not add explanation").
- On schema/JSON/ValueError failure with retries remaining, rebuilds messages with the assistant's bad output + correction prompt (`base_agent.py:130-142`). After exhaustion returns `(None, error, error_type, attempts)` → the agent wraps an `AgentError` (`analysis_agent.py:52-58`, etc.).
- **Analysis batch cross-record validation:** `validate_batch` requires returned IDs to equal input IDs **in order** (`analysis_agent.py:87-92`); mismatch raises ValueError → uses the same self-correction retries. On total batch failure it returns **one AgentError per review** so downstream counts stay aligned (`analysis_agent.py:101-110`) — a single bad batch of 10 costs 10 reviews (F13b).
- **Batch size:** `ANALYSIS_BATCH_SIZE = int(os.getenv("ANALYSIS_BATCH_SIZE", 10))` (`nodes.py:25`).

### 1.7 LLM provider layer — WHAT IS ACTUALLY CONFIGURED

- **Centralised in `backend/app/core/llm_config.py`.** Everything is OpenAI-shaped; provider chosen purely by env (`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_FALLBACK_MODEL`).
- **Code defaults: `primary_model()` → `gemini-2.5-flash` (`llm_config.py:62-63`), `fallback_model()` → `gemini-3.5-flash` (`llm_config.py:66-67`).** Same defaults duplicated in `strategy_agent.py:51-55` and `report_agent.py:47-51` (`os.getenv("OPENAI_MODEL","gemini-2.5-flash")` / `"gemini-3.5-flash"`) — these overwrite what `BaseAgent.__init__` already resolved (F11 defect, harmless because defaults match).
- **`.env.example`** (cloud profile) sets `OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`, `OPENAI_MODEL=gemini-2.5-flash`, `OPENAI_FALLBACK_MODEL=gemini-3.5-flash` (`.env.example:6-9`).
- **Local Ollama profile IS supported.** `.env.local.example` sets `OPENAI_BASE_URL=http://localhost:11434/v1`, `OPENAI_MODEL=llama3.1`, `OPENAI_FALLBACK_MODEL=llama3.1`, `OPENAI_API_KEY=ollama` (`.env.local.example:16-19`). `llm_config` detects local endpoints by substring (`localhost`, `127.0.0.1`, `0.0.0.0`, `:11434`, `ollama` — `llm_config.py:30`), injects placeholder key `"ollama-local"` when none set (`llm_config.py:35, 49-54`), and `is_configured()` returns True for a local endpoint even with no key (`llm_config.py:57-59`).
- **Provider label** recorded in eval dumps: `provider_label()` returns `"ollama-local (openai-compatible)"`, `"google-gemini (openai-compatible)"`, `"groq (openai-compatible)"`, or the raw URL (`llm_config.py:70-81`). `run_config()` = `{provider, base_url, primary_model, fallback_model}` (`llm_config.py:89-96`).
- **Fallback logic:** `_call_llm` catches any exception on the primary and retries once on the fallback model (`base_agent.py:88-99`).
- **Memory-note reconciliation:** the user's memory says *"code uses gemini-2.5-flash, CLAUDE.md says gpt-5.4"* — **VERIFIED**: code/`.env.example`/README/AGENTS all default to Gemini; only `CLAUDE.md` (Member-3 personal doc) still says gpt-5.4 (see DISCREPANCIES §2.1).

### 1.8 API endpoints + SSE contract (`backend/app/main.py`)

- `GET /health` → `{"status":"ok"}` (`main.py:96-98`). Does not check dataset/DB/key/provider (README §10).
- `GET /api/businesses/search?name=&top_n=3` → `list[BusinessMatch]`; 404 if none (`main.py:101-111`).
- `POST /api/reports` (body `ReportRequest`: restaurant_name, business_id?, sample_size?(ge=1,le=MAX_REVIEWS)) → `ReportResponse` (`main.py:114-158`). Resolves business (uses provided business_id or first fuzzy match — auto-selects best, `main.py:120-132`), loads+preprocesses, runs `run_pipeline`, maps `halted`→HTTP 500 (`main.py:147-150`), missing report→500 (`main.py:153-155`).
- `GET /api/reports/stream?restaurant_name=&business_id=&sample_size=` → SSE (`main.py:161-284`).
- **CORS is wildcard** (`allow_origins=["*"]`, `main.py:22-27`); no auth, no rate limits.
- **SSE event contract (new hub contract, `main.py:174-278`):** `stage_start` (`stage`, `attempt`), `stage_end` (`stage`, `attempt`, `duration_ms`, optional `info`), `verdict` (`stage`, `verdict`, `flags`, optional `detail`) emitted from the `orchestrator` node (`main.py:238-249`), `error` (`stage`, `detail`), `done` (`report`, `flags`). Data stages (`search_business`, `load_reviews`, `preprocess`) run outside the graph and are timed individually (`main.py:180-212`). A retried stage re-emits `stage_start` with `attempt+1` (`main.py:252-264`).
- `ReportResponse` extends `ReportOutput` with `analysis_summary`, `reasoning_summary`, `flags` (`main.py:48-51`). `_build_analysis_summary` computes sentiment/aspect counts in Python (`main.py:56-75`) — never LLM-generated (F9 note).

### 1.9 Frontend stack

- **Vite + React**, ES modules. Entry `frontend/src/main.jsx` → `App.jsx` (two-view nav: Dashboard / Pipeline Monitor, `App.jsx:6-31`).
- **Pinned versions (from `frontend/package-lock.json`):** react **19.2.7**, react-dom **19.2.7**, vite **8.0.16**, @vitejs/plugin-react **6.0.2**, lucide-react **1.17.0**. `package.json` declares all deps as **`"latest"`** (unpinned ranges).
- **No test framework dependency** — `"test": "node --test"` (`package.json:6`); client test `frontend/src/api/client.test.js`.
- **API client** `frontend/src/api/client.js`: `searchBusinesses` (default topN=5), `createReport` (POST), `streamReport` (EventSource). `API_BASE_URL` from `VITE_API_BASE_URL` else `http://localhost:8000` (`client.js:1`). **`streamReport` sends only restaurant_name + business_id — never `sample_size`** (`client.js:37-60`, confirms F11).
- Pages: `Dashboard.jsx`, `PipelineMonitor.jsx`; component `BusinessPicker.jsx`. **PipelineMonitor handles only `stage_start`/`stage_end`/`done`/`error` events and keys by `stage` alone — it does NOT consume the new `verdict` events and does NOT key by `(stage, attempt)`** (`PipelineMonitor.jsx:85-118`). UI text is in **Vietnamese**.
- Known UI gaps (README §11, AUDIT P2): Dashboard and Pipeline Monitor own separate state; switching restaurant can leave a stale report; accessibility gaps.

### 1.10 Evaluation harness — tiers, metrics, exact numbers

**Harness files** (`backend/eval/`): `common.py` (dump loader), `tier1_checks.py` (Tier 1 deterministic), `harness.py` (Tier 1b), `tier2_analysis.py` (Tier 2 gold), `tier3_judge.py` (Tier 3 LLM judge), `rubrics/*.md`, `gold/build_gold_jsonl.py`, `gold/tier2_gold_labeling_worksheet.xlsx`, `fixtures/sample_dump/`.

**Test restaurant / gold set:** **LOVE Grille**, Philadelphia, `business_id 4Env6uGYxMhXFKPfcuzUuQ`, 3.0★. **73 reviews** analysed (the full business, below the 100 cap). Confirmed: `backend/out/analysis.json` has **73 entries, all status=success**. (EVALUATION_REPORT §1.)

**Tier 1 — deterministic (24/25).** Source: `backend/out/tier1_report.json` (25 checks, 24 passed). Structure = 4 schema + 5 patterns × 3 checks (evidence_exists / aspect_present / frequency) + 2 strategy_traceability + 3 report_subset + 1 completion.
- The single failure: `groundedness:...food quality...:evidence_exists` — score **0.9655** (27/28 ids valid), detail `evidence_review_ids not found in analysis: ['SKXs-JiPXpVnAwcXhA5wA']`. The correct id has an extra "3" (`SKXs-JiPX3pVnAwcXhA5wA`). **Confirmed present in `out/reasoning.json`.** A caught, cosmetic transcription error (EVALUATION_REPORT §3).
- Sample passing detail lines: frequency `claimed=0.397, recomputed=0.40`; `claimed=0.384, recomputed=0.38`; `claimed=0.274, recomputed=0.27`; `claimed=0.219, recomputed=0.22`; `claimed=0.123, recomputed=0.12` (all within 0.05). Strategy: 5/5 issues traced, 4/4 priority pairs frequency-ordered. Report subset: 5/5 root causes, 5/5 recommendations verbatim, 5/5 key findings soft-match. `out/reasoning.json` = 5 patterns, 5 root_causes, status success.

**Tier 1b — reproducibility, latency, cost, degradation** (`harness.py`; numbers from EVALUATION_REPORT §4, PROSE ONLY — no committed JSON):
- Reproducibility: PASS (stable across two seed-42 runs).
- Latency (73 reviews): analysis **192.06 s**, reasoning **31.12 s**, strategy **16.82 s**, report **20.34 s**, total **260.33 s** → **356.62 s / 100 reviews** ("357s"). Tokens **108,270** → **148,315 / 100 reviews** ("148k"). Analysis ≈ 74% of wall time.
- **Degradation scenarios: the CURRENT `harness.py` has 8 scenarios (`check_degradation_paths`, `harness.py:96-202`), all passing (RUN_TESTS.md 2026-07-17 says 8/8).** EVALUATION_REPORT/README/PROGRESS still say **6/6** (stale — see DISCREPANCIES). The 8 named scenarios: healthy_analysis_proceeds, small_sample_flagged_low_confidence, insufficient_data_halts, critical_majority_failure_retries, critical_exhausted_halts, fabricated_evidence_retries, noncritical_gave_up_continues_on_record, report_gave_up_halts.

**Tier 2 — analysis gold set (`tier2_analysis.py`)** — sklearn `accuracy_score` + per-aspect binary `f1_score` macro-averaged (`tier2_analysis.py:135-181`). Numbers from EVALUATION_REPORT §5 (PROSE ONLY):
- **Sentiment accuracy 0.753 (55/73)**; **aspect macro-F1 0.852**; n=73.
- Per-aspect F1 (with gold support): cleanliness **1.000** (n=4), food_quality **0.975** (n=59), staff_attitude **0.966** (n=43), pricing **0.958** (n=34), wait_time **0.905** (n=22), other **0.734** (n=35), ambience **0.429** (n=3). cleanliness (n=4) and ambience (n=3) are low-support → indicative only. Single annotator (no Cohen's κ).

**Tier 3 — LLM-as-judge (`tier3_judge.py`)** — judge model **default `gemini-pro-latest`** (`tier3_judge.py:44`), distinct from pipeline model. Numbers from `backend/out/tier3_scores.json` (COMMITTED JSON EXISTS):
- `judge_model: "gemini-pro-latest"`, `pipeline_model: "gemini-2.5-flash"`.
- **means: root_cause_plausibility 4.8 (n=5), recommendation_actionability 4.2 (n=5), report_usefulness 5 (n=1).** Root causes: four 5s + one 4 (the vague "unspecified negative experiences"). Recommendations: four 4s + one 5 (the QR-code feedback system). Report: 5.
- NOTE: 2 of the justification strings in `out/tier3_scores.json` are malformed (nested JSON-in-string) but scores parsed fine.

**Rubrics:** `eval/rubrics/root_cause_plausibility.md`, `recommendation_actionability.md`, `report_usefulness.md` (1–5 scales).

**Fixture (`eval/fixtures/sample_dump/`):** synthetic "Example Bistro" (`EXAMPLE_biz_0001`); its `_summary.json` records `run_config` = google-gemini / gemini-2.5-flash / gemini-3.5-flash. Tier 1 fixture: 16/16 (README §12).

### 1.11 Test suite

- **119 tests collected; 113 offline pass, 6 integration deselected** (VERIFIED live: `pytest --collect-only` → "119 tests collected", "113/119 tests collected (6 deselected)" with `-m "not integration"`). Matches RUN_TESTS.md (2026-07-17). `pytest.ini` marks `integration` tests (`pytest.ini:4-5`).
- 15 test files (`def test_` counts): test_supervision.py **23** (new hub rules), test_unit.py 15, test_analysis_agent.py 12, test_orchestrator_routing.py 10, test_eval_tier1.py 9, test_report_agent.py 8, test_strategy_agent.py 8, test_llm_config.py 7, test_graph.py 5, test_data_pipeline.py 4, test_integration.py 4 (integration), test_api.py 2, test_orchestrator.py 2, test_e2e_pipeline.py 1 (integration), test_state.py 1. (111 raw `def test_`; 119 collected due to parametrization.)
- Coverage: preprocessing/fuzzy (test_unit), seeded raw/SQLite sampling + cap (test_data_pipeline), agent validation/retries (mocked), llm_config provider resolution, FastAPI POST/SSE contracts (test_api), hub measure/decide on real `out/` dumps + synthetic edges (test_supervision), hub graph wiring / routing / retry-feedback (test_graph, test_orchestrator*), deterministic eval regressions (test_eval_tier1). Live: test_integration + test_e2e_pipeline (uses in-memory reviews; e2e retries whole pipeline up to 3× per DECISIONS 2026-06-08).
- **Known gaps (RUN_TESTS.md):** no real 5.34 GB raw-loader perf regression; no SQLite-builder/partial-DB test; no frontend component/a11y/lint test; **no CI workflow**.

---

## 2. DISCREPANCIES (doc vs code, or doc vs doc)

### 2.1 Model family: CLAUDE.md vs everything else
- **CLAUDE.md** (root, Member-3 doc) §1/§5 says primary `gpt-5.4`, fallback `gpt-5.4-mini` (with `gpt-5`/`gpt-5-mini` fallbacks) and `OPENAI_MODEL=gpt-5.4`.
- **Code/`.env.example`/README §7/AGENTS.md §"Current Project Decisions"/DECISIONS 2026-07-14** all say primary **`gemini-2.5-flash`**, fallback **`gemini-3.5-flash`**.
- **Resolution:** Gemini is authoritative (DECISIONS 2026-07-14 "Approved model configuration" supersedes the GPT-5.4 target). CLAUDE.md is stale. The report must use Gemini, not GPT-5.4.

### 2.2 Orchestrator design: docs say "proposed/not implemented" — code says implemented
- `docs/ORCHESTRATOR_SIMPLE_HUB.md:3` "**Not yet implemented**"; `docs/ORCHESTRATOR_DESIGN.md:3` "Proposed. Not yet agreed, not yet implemented"; `docs/FINDINGS_2026-07-16.md` F7 describes the orchestrator as a linear-chain "exception handler."
- **Code reality:** the **simple hub (Option B) IS implemented and live** (`graph.py`, `supervision.py`, `orchestrator.py:43-54`, commit `953a6bd`). The graph is a hub (`graph.py:122-135`), the verdict set is `proceed|proceed_with_warning|retry|halt`, `skip` is dropped, frequency is Python-authoritative, retry-with-feedback works. **The report must describe the hub, not the old linear/error-handler chain, and must not cite FINDINGS F7's "linear chain / decide_recovery(no state)" as the current state.**
- README §5/§6/§9 and AGENTS.md:48 still describe the old design (README §6 "Retry, skip, or halt decisions after stage failure"; AGENTS.md:48 places orchestrator in `app/agents/` — it is in `app/core/`).

### 2.3 Test counts: README/PROGRESS/PROJECT_AUDIT (77/71) vs reality (119/113)
- README §12 & PROGRESS "Verified Checks" & PROJECT_AUDIT "Verification Snapshot": **77 collected / 71 offline passed** (2026-07-14).
- RUN_TESTS.md (2026-07-17) and **live verification here: 119 collected / 113 offline / 6 deselected.** Use 119/113.

### 2.4 Degradation scenarios: 6/6 vs 8/8
- EVALUATION_REPORT §4, README §13/§12, PROGRESS, DECISIONS 2026-07-15: **6/6**.
- Current `harness.py:96-202` and RUN_TESTS.md: **8/8**. Use 8/8 (matches code).

### 2.5 `out/_summary.json` lacks `run_config` — provenance claim not backed by the committed Gemini dump
- README §7 / DECISIONS 2026-07-14 claim every run records `run_config` in `_summary.json`, and this is the provenance evidence for the Gemini 73-review evaluation.
- **`backend/out/_summary.json` (the Gemini LOVE Grille run cited by EVALUATION_REPORT) contains NO `run_config` field** (only business_name, business_id, pipeline_status, skipped_agents, failed_agent, errors, retry_counts). It also lacks `flags`/`last_verdict` that current `run_pipeline._dump_stages` writes (`run_pipeline.py:119-130`) → this dump predates the current dump code. The Gemini provenance for the headline eval numbers is **prose-only**, not in the committed JSON.
- Only `eval/fixtures/sample_dump/_summary.json` (synthetic) and `out_hub/_summary.json` carry `run_config`.

### 2.6 The committed hub live run (`out_hub/`) is Groq, not Gemini or local Ollama
- `backend/out_hub/_summary.json` `run_config` = **provider `groq (openai-compatible)`, base_url `https://api.groq.com/openai/v1`, primary `llama-3.3-70b-versatile`, fallback `llama-3.1-8b-instant`.** (RUN_TESTS.md:116 confirms "Groq llama-3.3-70b: 22/22".) `out_hub/tier1_report.json` = 22 checks, all pass (4 patterns × 3 + 4 schema + 2 strategy + 3 report + 1 completion). So the only committed *hub* live dump was produced on **Groq**, contradicting README's "cloud Gemini / local Ollama" framing. There is **no committed local-Ollama run** anywhere.

### 2.7 EVALUATION_REPORT date vs content
- `docs/EVALUATION_REPORT.md` header dated **2026-07-10**, but describes the 73-review live run that DECISIONS/PROGRESS date to **2026-07-15**. Internal date inconsistency.

### 2.8 SQLite index status: README "Not built" vs reality "present"
- README §"Current Status" line "Local SQLite index — Not built in the audited checkout" and §15 P1 risk; PROGRESS "Implemented, not built locally"; PROJECT_AUDIT Verification Snapshot "SQLite index was absent."
- **Reality (this checkout): `backend/data/processed/yelp.db` EXISTS.** FINDINGS F12 and PROJECT_AUDIT "Update 2026-07-16" already flag these lines as stale. Use "present."

### 2.9 README repo-structure diagram references a deleted file
- README §"Repository Structure" lists `docs/CLAUDE.md`. **`docs/CLAUDE.md` does not exist** (only root `CLAUDE.md` does). FINDINGS F12 confirms it was deleted. DECISIONS 2026-06-08 said CLAUDE.md lives in `docs/`; it is actually at root.

### 2.10 `docs/LOCAL_LLM.md` referenced 8× but never existed
- Referenced from README:182, AGENTS.md:32, RUNNING.md:11 & :151, RUN_TESTS.md:18, DECISIONS.md:38, PROJECT_AUDIT.md, `llm_config.py:12` & `:102`, and the **report skeleton §3**. **VERIFIED absent** (`ls docs/LOCAL_LLM.md` → not found; `git log --all` returns nothing per FINDINGS F12). The local profile is genuinely implemented; only the walkthrough doc is missing.

### 2.11 Contract note: README §11 vs contracts.py — consistent
- README §8/§11 report schema and error schema match `contracts.py` exactly (`ReportOutput`, `AgentError`). CLAUDE.md §4 contracts also match. No field-name drift found. (One nuance: `RootCause` has no `evidence_review_ids` despite CLAUDE.md §4.4 not requiring it — consistent.)

### 2.12 `_error()` shape bug (report agent)
- `report_agent.py:54-55` `_error()` returns a `"recommendations"` key (copy-pasted from strategy agent) instead of report fields. Harmless (callers read only status/error_detail) but the report error payload carries another agent's field (FINDINGS F11).

---

## 3. STALE / UNRESOLVED — the report must NOT claim these

- **Do not present the orchestrator as an "exception handler / linear chain" (FINDINGS F7) — that is superseded.** Do not claim `decide_recovery` takes no state as the current design. Present the implemented **simple hub**.
- **`docs/ORCHESTRATOR_DESIGN.md` (Option A, full validator-node redesign) is NOT implemented.** It remains a proposal. `n_relevant`, `relevant: bool` on `AnalysisOutput`, confidence intervals, impact-weighted strategy priority, a separate `validator_node`, and LLM-escalation are all deferred (ORCHESTRATOR_SIMPLE_HUB §4 "the honest 20%"). Do not claim confidence intervals or `n_relevant` exist.
- **F2b/F3 NOT implemented:** reasoning still receives only `review_id`/`sentiment`/`aspects` (`nodes.py:110-119`); `text`, `date`, `stars` still do not reach reasoning. Root causes are inferred from aspect statistics, not text. No temporal reasoning.
- **F1 (statistical qualification) NOT resolved:** `Pattern.frequency` is still a bare proportion with no CI and no `n` propagated. `confidence` is LLM-assigned. Median business ≈ 15 reviews (FINDINGS F1). The hub adds a `low_confidence:n=<n>` flag when n<30 but does not compute CIs.
- **F13a NOT fully wired into scoring:** the hub `measure` computes a stars-vs-sentiment `contradiction_rate` (`supervision.py:124-143`) and gates retry at >0.20 — but Tier 2 scoring (`tier2_analysis.py`) still does not use stars as a cross-check.
- **F5 NOT resolved:** no groundedness check for `root_causes` in Tier 1 (`tier1_checks.py` covers patterns only).
- **F6/F10/F13b open** (design notes/defects): 100-cap inactive for ~90% of businesses; analysis proceeds at exactly 50% failure; one failed batch discards 10 reviews.
- **PROJECT_AUDIT open limitations:** (P1) business identity/name accepted independently + no fuzzy-match minimum threshold (still open — `matching.py` has no floor, `main.py:120-132` auto-selects first match); (P1) `build_db.py` non-atomic — writes directly to final path, drops tables at start (`build_db.py:78-87, 126-137`), `_db_available()` only checks `os.path.exists` → interrupted build leaves a partial DB treated as valid; (P2) frontend stale/duplicated state; (P2) accessibility gaps; (P2) local-demo security only (wildcard CORS, no auth/rate-limit, raw SSE errors — `main.py:22-27, 277-278`); (P2) unpinned deps.
- **`openpyxl` missing from `requirements.txt`** though `eval/gold/build_gold_jsonl.py` needs it (EVALUATION_REPORT §7). `requirements.txt` also lists **unused `fuzzywuzzy` + `python-levenshtein`** (rapidfuzz is what's used) — AUDIT P2.
- **No CI workflow** exists (README §13, RUN_TESTS.md, eval/README.md).
- **`config.py` `Settings`** is dead relative to the loader (loader reads env directly).
- **Do not claim a completed local-vs-cloud comparison** — none exists.

---

## 4. REPORT DATA PACK

### 4.1 Library table (backend — `backend/requirements.txt`, UNPINNED)

| Library | Version | Purpose |
|---|---|---|
| fastapi | unpinned | HTTP API framework (endpoints, SSE) |
| uvicorn[standard] | unpinned | ASGI server |
| pandas | unpinned | Review DataFrame handling / preprocessing |
| pydantic | unpinned (v2) | Structured inter-agent contracts + validation |
| python-dotenv | unpinned | Load `.env` provider config |
| rapidfuzz | unpinned | Fuzzy business-name matching |
| openai | unpinned | OpenAI-compatible LLM client (Gemini/Ollama/Groq) |
| langchain | unpinned | LLM framework base |
| langgraph | unpinned | Multi-agent pipeline graph |
| fuzzywuzzy | unpinned | (listed but UNUSED — rapidfuzz replaced it) |
| python-levenshtein | unpinned | (fuzzywuzzy backend — effectively unused) |
| langchain-openai | unpinned | `ChatOpenAI` used by orchestrator recovery LLM |
| pytest | unpinned | Test runner |
| scikit-learn | unpinned | Tier 2 accuracy + macro-F1 |
| *openpyxl* | *MISSING* | *Needed by `eval/gold/build_gold_jsonl.py`; not in requirements* |

### 4.2 Library table (frontend — versions from `frontend/package-lock.json`; `package.json` declares `"latest"`)

| Library | Installed version | Purpose |
|---|---|---|
| react | 19.2.7 | UI library |
| react-dom | 19.2.7 | React DOM renderer |
| vite | 8.0.16 | Dev server / build tool |
| @vitejs/plugin-react | 6.0.2 | React plugin for Vite |
| lucide-react | 1.17.0 | Icon set |

### 4.3 API endpoint table

| Method | Path | Query/Body | Returns |
|---|---|---|---|
| GET | `/health` | — | `{"status":"ok"}` |
| GET | `/api/businesses/search` | `name`, `top_n`(=3) | `list[BusinessMatch]`; 404 if none |
| POST | `/api/reports` | body: `restaurant_name`, `business_id?`, `sample_size?`(1–100) | `ReportResponse`; 500 on halt/no-report |
| GET | `/api/reports/stream` | `restaurant_name`, `business_id?`, `sample_size?` | SSE: `stage_start`/`stage_end`/`verdict`/`error`/`done` |

### 4.4 Eval results tables (exact numbers)

**Tier 1 (source `out/tier1_report.json`):** 25 checks, **24 pass / 1 fail**. Fail = evidence_exists on the food-quality pattern, score 0.9655 (27/28 ids), mistyped id `SKXs-JiPXpVnAwcXhA5wA`. Fixture Tier 1 = 16/16. Hub Groq run (`out_hub/tier1_report.json`) = 22/22.

**Tier 1b (prose in EVALUATION_REPORT §4):**

| Stage | Time (73 reviews) |
|---|---|
| analysis | 192.06 s |
| reasoning | 31.12 s |
| strategy | 16.82 s |
| report | 20.34 s |
| total | 260.33 s → **356.62 s / 100 reviews** |
| tokens | 108,270 → **148,315 / 100 reviews** |

Reproducibility PASS; degradation **8/8** (current harness) — but EVALUATION_REPORT/README say 6/6.

**Tier 2 (prose in EVALUATION_REPORT §5; no committed JSON):** sentiment accuracy **0.753 (55/73)**, aspect macro-F1 **0.852**, n=73.

| Aspect | F1 | gold support |
|---|---|---|
| cleanliness | 1.000 | 4 |
| food_quality | 0.975 | 59 |
| staff_attitude | 0.966 | 43 |
| pricing | 0.958 | 34 |
| wait_time | 0.905 | 22 |
| other | 0.734 | 35 |
| ambience | 0.429 | 3 |

**Tier 3 (source `out/tier3_scores.json`):** judge `gemini-pro-latest`, pipeline `gemini-2.5-flash`. Means: root_cause_plausibility **4.8** (n=5), recommendation_actionability **4.2** (n=5), report_usefulness **5.0** (n=1).

### 4.5 Agent role summaries (grounded in code)

- **Analysis Agent** (`analysis_agent.py`): classifies each review's overall `sentiment` (positive/negative/neutral/mixed) and per-aspect `label` over the 7 `AspectCategory` values. Batches 10 reviews/LLM call (`nodes.py:25`); enforces returned IDs == input IDs in order (`analysis_agent.py:87-92`); on total batch failure emits one `AgentError` per review. Two self-correction retries via `BaseAgent`. Only stage with objective gold labels.
- **Reasoning Agent** (`reasoning_agent.py`): given the successful analysis rows (id/sentiment/aspects only), emits recurring negative `patterns` (description, aspect, frequency, evidence_review_ids) and `root_causes` (pattern, cause, confidence). Frequency it claims is overwritten by Python post-hoc (`supervision.apply_frequency_corrections`). No review text/date reaches it.
- **Strategy Agent** (`strategy_agent.py`): converts patterns+root_causes into prioritised `Recommendation`s (priority≥1, issue, action, category, expected_impact). Has an LLM mode (default, `use_llm=True`) and a deterministic mode (`_deterministic_recommendations`, ranks by confidence then frequency). Consumed by report; validated by hub for traceability (`< 0.35` similarity → retry).
- **Report Agent** (`report_agent.py`): assembles the final `ReportOutput` (title, business_name, sample_size, executive_summary, key_findings, root_causes, recommendations, limitations). Overwrites `business_name`/`sample_size` from trusted input (`report_agent.py:133-134`). LLM + deterministic modes. `analysis_summary` passed in is empty `{}` (`nodes.py:160`); the UI summary is computed in `main.py` instead.
- **Orchestrator** (`orchestrator.py` + `graph.py` + `supervision.py`): the hub. After each stage, `measure()` computes deterministic facts from state and `decide()` returns `proceed|proceed_with_warning|retry|halt` by hard rules (no LLM on the common path). Writes `retry_feedback`, `flags`, `last_verdict`; enforces the 2-retry cap; overwrites pattern frequencies. Critical stages (analysis, reasoning) halt on unrecoverable failure; non-critical (strategy, report) can be abandoned-on-record.

### 4.6 Git-history member attribution

Contributor identities (from `git shortlog -sne`):
- **Pham Ho Quang Dung** `<qdung2k3@gmail.com>` — **Member 3** (the repo user, "Dung"). 16 commits. Branch **`dung/analysis-reasoning-agent`**.
- **TranManhDuc / TranDuc511** `<manhducpc05@gmail.com>` — "Duc"; **repo owner** (`github.com/TranDuc511/...`), merged PRs #7–#12. 14+3 commits.
- **khanhnedu2006-byte / Khanh Nguyen** `<khanhn.edu2006@gmail.com>` — **Member 2** ("Khanh"), data pipeline. Branch **`feature/khanh-data`**. 6+5 commits.
- **Hahhahahaadsa / HoangHuuHoan** `<hoanhandsome207@gmail.com>` — "Hoan", evaluation + core/orchestration. 9+2 commits. Branch **`eval/tier2-full-73-gold`**.

Attribution by area (commits touching path):
- Analysis/Reasoning agents → mostly **Dung** (Member 3) — consistent with CLAUDE.md scope.
- `app/data/` → mostly **Khanh** (Member 2) — see `Member2 changes report.MD` (author "Khánh").
- `backend/eval/` → mostly **Hoan** (Hahhahahaadsa, 4 commits) + Dung.
- `app/core/` (graph/orchestrator/supervision) → **Hoan** (3) + **Dung** (2) + Duc + Khanh.
- `frontend/` → **Dung** (2) + **Duc** (2) + Khanh.

Branches: `main`, `dung/analysis-reasoning-agent`, `feature/khanh-data`, `eval/tier2-full-73-gold`, `setup-folder-structure`. Merged PRs #7–#12. Simple-hub delivered by commit `953a6bd` (feat: simple-hub orchestrator Option B). **Roles map cleanly to the report skeleton's suggested split** (M1 analysis/lead, M2 data pipeline & matching, M3 orchestration & evaluation) — but note the code shows Dung owning analysis+reasoning agents, Khanh owning data, Hoan owning eval+core.

### 4.7 Demonstration-scenario evidence that EXISTS

- **End-to-end run artifacts:** `backend/out/` (Gemini 73-review LOVE Grille: `analysis.json` 73 entries, `reasoning.json` 5 patterns/5 causes, `strategy.json`, `report.json`, `tier1_report.json` 24/25, `tier3_scores.json`). `_summary.json` lacks run_config (see §2.5).
- **Hub live run artifacts:** `backend/out_hub/` (Groq llama-3.3-70b, 73 reviews, `tier1_report.json` 22/22, `_summary.json` with run_config groq).
- **Offline fixture:** `backend/eval/fixtures/sample_dump/` (synthetic Example Bistro, run_config gemini) — reproducible Tier 1 = 16/16.
- **Provenance file with run_config:** only `out_hub/_summary.json` (groq) and `fixtures/sample_dump/_summary.json` (gemini). Use these to evidence the "run_config recorded per run" claim.
- **Degradation evidence:** deterministic, reproducible via `python -m eval.harness --skip-live` (8 scenarios, no API needed).

---

## 5. MISSING FOR REPORT (does not exist; needs a human or a live run)

1. **`eval/gold/tier2_scores.json` and `eval/gold/analysis_gold.jsonl` DO NOT EXIST** anywhere in the repo (verified: `find` returns nothing; `eval/gold/` contains only `build_gold_jsonl.py` and the `.xlsx` worksheet). The report skeleton §5.3 says "numbers in eval/gold/tier2_scores.json" — that file is not present. **The Tier 2 numbers (0.753, 0.852, per-aspect table) exist only as prose in `docs/EVALUATION_REPORT.md`; there is no committed JSON backing them, and the gold JSONL to reproduce them is absent.** A live Tier 2 run (`build_gold_jsonl.py` on the worksheet, then `tier2_analysis.py`) is needed to regenerate them — and requires `openpyxl` (not in requirements) + the SQLite index.
2. **Latency/cost JSON:** the 356.62 s / 148,315 tokens per-100-review figures are prose-only (`harness.py` prints, does not dump JSON). Re-run `eval.harness` to capture defensible current numbers (ideally on the hub graph).
3. **Local-vs-cloud comparison (skeleton §5.6 / §8.2):** no local-Ollama run exists; the only non-Gemini committed dump is Groq (`out_hub/`). A genuine Ollama run (`.env.local.example`) producing `run_config = ollama-local` is required. No paired quality/latency/cost comparison exists.
4. **`docs/LOCAL_LLM.md`:** referenced 8× (incl. report skeleton §3) but never existed. Must be written to close the Option-D local-LLM evidence requirement.
5. **UI screenshots (skeleton §6):** NO image files anywhere (`find` for png/jpg/svg/etc. returns nothing). Search UI, live SSE pipeline progress, and final report screenshots must be captured from a live run.
6. **Student full names + IDs + supervisor + semester:** all placeholders in `COS30018_Report_Skeleton.docx`; not in the repo. Team-supplied. (Contributor emails are known — see §4.6 — but not IDs.)
7. **Tier 3 on the hub/Gemini current run:** the committed `out/tier3_scores.json` corresponds to the older Gemini `out/` dump; if the report presents the hub pipeline, a fresh Tier 3 judge run on a current dump is advisable (the hub `out_hub/` dump has no tier3_scores.json).
8. **Second Tier 2 annotator / Cohen's κ:** single-annotator gold set (EVALUATION_REPORT §5); inter-annotator agreement is the one open item for full Tier 2 defensibility.
9. **Fresh, run_config-bearing end-to-end dump on the intended demo provider:** the committed Gemini `out/_summary.json` lacks `run_config`; a re-run with the current `run_pipeline.py --dump-stages` would produce a summary carrying `run_config`, `flags`, and `last_verdict` for clean provenance.

---

### Appendix — quick provenance of key numbers

| Claim | Where it lives | Backed by committed data? |
|---|---|---|
| 73 reviews, LOVE Grille, 4Env6uGYxMhXFKPfcuzUuQ | EVAL_REPORT §1 | YES — `out/analysis.json` (73 entries) |
| Tier 1 24/25, mistyped id | EVAL_REPORT §3 | YES — `out/tier1_report.json`, `out/reasoning.json` |
| Latency 356.62 s/100, 148,315 tok/100 | EVAL_REPORT §4 | NO — prose only |
| Degradation 6/6 | EVAL_REPORT §4 | STALE — code is 8/8 |
| Tier 2 0.753 / 0.852 + per-aspect | EVAL_REPORT §5 | NO — prose only; no gold JSONL / tier2_scores.json |
| Tier 3 4.8 / 4.2 / 5.0, judge gemini-pro-latest | EVAL_REPORT §6 | YES — `out/tier3_scores.json` |
| run_config gemini for the eval | README §7 | PARTIAL — only fixture; `out/_summary.json` has none; hub run is Groq |
| 119/113 tests | RUN_TESTS.md | YES — verified via `pytest --collect-only` |
