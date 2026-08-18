# Project Strengths and Weaknesses Audit

**Audit date:** 2026-07-14
**Last updated:** 2026-07-16 — snapshot corrections; see "Update 2026-07-16" below
**Scope:** backend, data pipeline, LangGraph recovery, schemas, FastAPI,
frontend, tests, evaluation, configuration, and documentation.

> **How to read the Verification Snapshot.** It records one run, on one
> contributor's machine, on 2026-07-14. Several lines describe *that machine's
> local state* (which Python was installed, whether a git-ignored SQLite index
> existed), not the state of the project — those lines will not match your
> checkout and are not defects. Lines describing *code* (test counts, build
> results) should match any checkout at the same commit. The snapshot is
> preserved verbatim as a historical record; corrections are in the update
> section below rather than edited into it.

## Update 2026-07-16

Verified on a different contributor's machine (Khanh) at commit `f13b2a9`.

**Machine-local lines that do not generalise.** The audit ran on the machine of
the `27c0399` author. On the checkout audited on 2026-07-16:

| Snapshot line | This checkout | Nature |
|---|---|---|
| "Python 3.10.19 environment" | Python **3.13.12** (`venv` created 2026-05-28) | machine-local |
| "SQLite index was absent" | **present** — 5.4 GB, built 2026-06-24 (mtime and ctime both 2026-06-24, so not copied in later) | machine-local |
| "raw review lookup scanned 5.34 GB in 77.48 seconds" | not reproducible — with the index present, `loader._db_available()` returns `True` and the raw path is never taken | consequence of the above |

**Code-level line that was stale on arrival.** The snapshot reports 77 tests
collected / 71 offline passed. The actual counts at that same commit are **92 /
86** (6 integration deselected — that figure is correct). The difference is
exactly 15, which is the size of `tests/test_llm_config.py`, added by commit
`27c0399` — the very commit that carries this audit. The tests were run, the
audit was written, then the new test file was added, and all of it was committed
together. Nothing was fabricated; the numbers were simply overtaken before the
commit landed.

**Consequence for the reader.** Three findings below (the SQLite gate in
"P1: Current data path is slow", the "Minimum Repair Order" item 3, and the
"Demo Readiness Gate") were written assuming no index exists. On a checkout
where the index has been built, they are already satisfied. They remain valid
for any contributor who has not built it, since the file is git-ignored by
design.

**Also on 2026-07-16:** `docs/LOCAL_LLM.md`, referenced at line 181 below and
from seven other places, does not exist and never has (`git log --all` returns
nothing for that path). See `docs/FINDINGS_2026-07-16.md` F12.

**Findings not covered by this audit.** Twelve further findings — including a
P0 concerning the median 15-review sample size, and a P1 architecture drift in
the Orchestrator — are recorded in `docs/FINDINGS_2026-07-16.md`. That document
is an addendum to this one, not a replacement.

## Verdict

The repository is a solid course prototype with clear architecture, structured
LLM outputs, a working API/frontend path, and strong deterministic evaluation.
The two original P0 defects and the scoped contract/API/frontend P1 defects are
fixed and regression-tested. Remaining business-identity, model-configuration,
data-index, real-data, component, and CI risks still block a production claim.

## Verification Snapshot

- Git worktree was clean before the documentation update.
- Python 3.10.19 environment passed `pip check`.
- 77 backend tests collected.
- 71 offline backend tests passed.
- 6 live integration tests were deselected.
- 2 frontend API-client tests passed.
- Tier 1 fixture passed 16/16 checks.
- Synthetic degradation harness passed 6/6 scenarios.
- Frontend production build passed; JavaScript bundle was 68.13 kB gzip.
- Raw Yelp files were present.
- SQLite index was absent.
- One real raw review lookup scanned 5.34 GB in 77.48 seconds.

Live LLM tests were not rerun because they incur external API usage. The live
E2E test uses a fixed in-memory sample and does not validate the raw Yelp or
FastAPI path.

## Strengths

### 1. Clear architecture

The project separates:

- data loading, matching, and preprocessing;
- agent logic;
- graph/state/orchestration;
- Pydantic contracts;
- FastAPI delivery;
- React presentation;
- offline and live evaluation.

The CLI and API reuse the production pipeline nodes instead of maintaining
separate implementations.

### 2. Structured LLM boundary

`BaseAgent` centralises:

- OpenAI-compatible calls;
- JSON response mode;
- Pydantic validation;
- correction prompts;
- two self-correction retries;
- configured fallback model calls;
- token accounting for evaluation.

Contracts constrain sentiments, aspects, frequencies, evidence presence,
recommendation priorities, report sections, status, and errors.

### 3. Strong deterministic evaluation

Tier 1 checks more than execution success. It verifies:

- schema validity;
- evidence IDs;
- evidence aspect alignment;
- frequency recomputation;
- recommendation traceability;
- report subset consistency;
- pipeline completion.

The committed fixture is small, deterministic, offline, and appropriate for
future CI.

### 4. Practical data design

Strengths include RapidFuzz, business caching, parameterized SQLite queries,
analysis batching, and raw-file fallback. The SQLite index avoids repeated
full-file scans when it exists.

### 5. Functional frontend

The React application includes:

- branch confirmation;
- a report dashboard;
- sentiment and aspect summaries;
- evidence counts;
- root causes and recommendations;
- limitations;
- SSE pipeline progress and timings.

The production build passes.

### 6. Secret and artifact hygiene

Real environment files, raw Yelp files, generated databases, JSONL, CSV,
Parquet, and build outputs are ignored. No live credential was found in tracked
text during the audit.

## Resolved P0 Findings

### Resolved P0: Sampling methodology

The loader now:

- validates `MAX_REVIEW_SAMPLE` from 1 to 100;
- sorts candidates by review ID to remove storage-order dependence;
- samples with `RANDOM_SEED`;
- applies optional request caps in POST, SSE, and CLI paths;
- uses the same sampling helper for raw JSON and SQLite.

Regression coverage verifies repeatability, raw/SQLite parity, non-recency, and
cap validation.

### Resolved P0: Chained recovery

Production nodes now record the current error and clear recovered state at node
boundaries. Failure inference inspects current outputs from report backward to
analysis before consulting explicit routing state.

Graph recovery stops after two retries. Recovery-provider exceptions and invalid
responses retry deterministically while attempts remain; exhausted critical
stages halt and exhausted non-critical stages skip.

A regression reproduces consecutive reasoning and strategy failures, verifies
the correct error detail for each stage, and terminates with the intended skip.

## Resolved P1 Findings

### Resolved P1: Cross-record and trusted metadata invariants

Analysis batch output now enters the normal self-correction path unless its
review IDs exactly equal the input IDs in the original order. This enforces
count, equality, ordering, and duplicate detection without a second retry loop.

Report business name and sample size are overwritten from validated report
input, and the POST/SSE response builders overwrite them again from application
business input and preprocessed sample state. Business ID/name consistency is a
separate unresolved finding. Regressions cover incomplete/reordered batches and
wrong model-generated report metadata.

### Resolved P1: API/frontend client boundaries

Offline FastAPI `TestClient` regressions cover POST report responses, SSE event
delivery, and trusted final metadata. Node's built-in test runner covers frontend
search/report requests, SSE parsing, URL encoding, and connection-error closure.
No frontend testing dependency was added.

## Remaining Weaknesses

### P1: Business identity and matching are weak at the API boundary

`business_id` and `restaurant_name` are accepted independently. Direct API
clients can label one business's reviews with another name.

Fuzzy matching has no minimum acceptance score. Nonsense queries still produce
low-score matches, and the report endpoint auto-selects the first result when no
business ID is supplied.

### Resolved P1: Model configuration is now single-source and recorded

Approved configuration: provider Google Gemini (OpenAI-compatible endpoint),
primary `gemini-2.5-flash`, fallback `gemini-3.5-flash` (a *distinct* model, so
fallback resilience is restored). Set as the default in the agents,
`orchestrator.py`, and `.env.example`, and reconciled in `AGENTS.md`/`README`.

Provenance: every run records the configuration actually used in the evaluation
dump (`_summary.json -> run_config`), so results are attributable even when a
local `.env` overrides the defaults. The agents are provider-agnostic (the
OpenAI-compatible endpoint is chosen by environment), so the same code runs on
cloud Gemini or a local Ollama model (`backend/.env.local.example`), satisfying
the local-and-cloud requirement. See docs/DECISIONS.md (2026-07-14).

> **Correction (2026-07-16).** This section originally also pointed to
> `docs/LOCAL_LLM.md`. That file does not exist and never has — `git log --all`
> returns nothing for the path, and it is referenced from seven other places
> besides this one. The local profile is genuinely implemented
> (`backend/.env.local.example`, `app/core/llm_config.py`), so the *decision*
> stands; only its walkthrough is missing. Because that walkthrough is the
> written evidence for the Option-D local-LLM requirement, this is worth closing
> early. See `docs/FINDINGS_2026-07-16.md` F12.

### P1: Index creation is not atomic (the "slow path" half is machine-local)

*Machine-local half — resolved on some checkouts.* The machine audited on
2026-07-14 had no SQLite DB, so every report scanned 5.34 GB before LLM
processing. This does not apply where `scripts/build_db.py` has been run: the
2026-07-16 checkout has a 5.4 GB index built on 2026-06-24, and `loader`
switches to it automatically. The DB is git-ignored by design, so this remains
true for any contributor who has not built it — it is a per-machine setup step,
not an open code defect.

*Still open on every checkout.* `build_db.py` writes to the final path and
commits intermediate tables. An interrupted build can leave a partial DB that
`_db_available()` treats as valid, since it only tests `os.path.exists`. This is
the real defect in this section and it is unchanged.

### P1: Data, component, and CI boundaries lack tests

Missing automated coverage:

- real-dataset raw-loader behavior and performance;
- SQLite builder and partial DB handling;
- frontend component interactions;
- accessibility;
- CI execution.

The live E2E test bypasses Yelp data and FastAPI and retries the full paid
pipeline up to three times.

### P2: Frontend state can be stale or duplicated

Dashboard and Pipeline Monitor own separate state and can execute the same
expensive pipeline independently. Switching views discards the current stream.
Selecting another restaurant does not clear the previous report.

### P2: Accessibility needs hardening

Known gaps:

- removed focus outlines without complete replacements;
- asynchronous messages without live regions;
- active navigation without state semantics;
- pipeline state communicated mainly by color/icons;
- some small-text color combinations below WCAG AA contrast.

### P2: Local-demo security only

The API has wildcard CORS, no authentication, no rate limits, and no LLM cost
controls. SSE returns raw exception details. This is acceptable only on a trusted
local network.

### P2: Reproducibility and documentation drift

Python dependencies are unpinned and include unused fuzzy-matching packages.
Frontend manifest ranges use `latest`, though the lockfile pins the current
installation.

Before this update, documentation contradicted the code about API wiring,
frontend status, SQLite support, providers, test counts, and evaluation status.

## Minimum Repair Order

1. Add a fuzzy-match threshold and validate business ID/name consistency.
2. Done - approved configuration (gemini-2.5-flash / gemini-3.5-flash) is set
   everywhere and recorded per run in the eval dump `run_config`.
3. Build SQLite atomically and validate schema/completeness before use.
   *(2026-07-16: an index exists on at least one checkout, so the "build it"
   half is done there. The atomicity and validation half is untouched.)*
4. Add real-data, frontend component, accessibility, and CI checks.

This order predates `docs/FINDINGS_2026-07-16.md`, which raises a P0 (statistical
claims unqualified on a median 15-review sample) and a P1 architecture drift in
the Orchestrator. Neither is reflected in the ordering above; the two documents
should be reconciled before the list is used to plan work.

## Demo Readiness Gate

The sampling and chained-recovery gates now pass. Demo readiness still requires:

- a built and validated SQLite index — *built* on the 2026-07-16 checkout;
  *validated* is still open (see the atomicity gap above);
- the actual model/provider is recorded (done - eval dump `run_config`);
- one real dataset + API + frontend run is completed successfully.

## Audit Limitations

- No live LLM request was made during this audit.
- No browser automation or Lighthouse audit was run.
- Coverage percentage is unknown because coverage tooling is not installed.
- Security review was static and local; no penetration test was performed.
- **The Verification Snapshot reflects one machine.** Lines about the installed
  Python and the presence of the git-ignored SQLite index describe the auditing
  contributor's local setup, not the project. A future audit should either state
  which machine it ran on, or separate machine-local observations from
  code-level ones. See "Update 2026-07-16".
- **Test counts can go stale within their own commit.** The snapshot's 77/71
  was correct when measured and wrong when committed, because `27c0399` added
  15 tests after the run. Re-run counts immediately before committing an audit.
