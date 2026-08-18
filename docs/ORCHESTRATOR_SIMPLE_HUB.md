# Orchestrator Simple Hub — Alternative to the Full Redesign

**Status:** Proposed alternative. Not yet agreed by the team, not yet implemented.
**Date:** 2026-07-17
**Author:** Member 3
**Related:** `docs/ORCHESTRATOR_DESIGN.md` (the full design), `docs/FINDINGS_2026-07-16.md` (F1, F2a, F4, F7, F13a)

This document proposes a smaller first step toward the hub architecture. It
delivers the same supervision behaviour on every run, with **no contract
changes, no new validator node, and no new state schema beyond three fields**,
and it migrates cleanly to the full design later. It also records three defects
found in the full design document that the team should resolve regardless of
which option is chosen (§6).

Per `AGENTS.md:77` ("Distinguish agreed target behavior from current
implementation behavior"), this spec is recorded *before* any code changes.
Nothing here describes existing behaviour.

---

## 1. TL;DR

| | Option A — Full design (`ORCHESTRATOR_DESIGN.md`) | Option B — Simple hub (this doc) |
|---|---|---|
| Graph shape | agent → **validator node** → orchestrator → next | agent → orchestrator → next |
| Where measuring lives | separate `validator_node`, dispatched via `current_stage` | plain function `measure(stage, state)` inside the orchestrator node |
| Contract changes required first | **Yes** — F2a (`frequency` out of LLM contract), F14 (`relevant: bool`) | **None** |
| New state fields | 5 (`current_stage`, `completed_stages`, `validation`, `flags`, `n_relevant`) | 3 (`flags`, `retry_feedback`, `last_verdict`) |
| Verdicts | proceed / proceed_with_warning / retry / skip / halt | proceed / proceed_with_warning / retry / halt (**skip dropped**, §6.1) |
| LLM escalation path | optional, open question | none — fully deterministic |
| Test files to rewrite | ~8 of 16 | ~4-5 of 16 |
| Downstream impact (Member 4/5, frontend, gold set) | contract ripples | none |
| Value delivered | 100% of the design | ~80% (§4 lists the exact 20% deferred) |

Both options share three unavoidable costs (§5). Option B is a strict subset of
Option A structurally: upgrading later means extracting one function into a
node, not rebuilding.

---

## 2. Graph shape (Option B)

```
preprocess → analysis → ORCH → reasoning → ORCH → strategy → ORCH → report → ORCH → END
                          │
                          ├─ retry → re-run the agent that just ran (with feedback, §5.3)
                          └─ halt  → END
```

The existing `error_handler_node` (`graph.py:82`) already sits in the right
place and already does half of this job — Option B **extends it into the happy
path** rather than adding new machinery. `_infer_failed_agent` (`graph.py:59`)
already demonstrates the stage-inference technique, so no `current_stage`
bookkeeping is needed.

```python
def orchestrator_node(state):
    stage   = _latest_stage(state)          # same technique as _infer_failed_agent
    facts   = measure(stage, state)         # pure function, unit-testable alone
    verdict = decide(stage, facts, state.get("retry_counts", {}))
    # write last_verdict, flags, retry_feedback;
    # pipeline_status stays terminal-only (§6.2)
```

`measure` and `decide` are plain functions in one module
(`app/core/supervision.py`, proposed). They are the future validator: Option
A's `validator_node` is `measure` moved behind a node boundary.

## 3. Why no contract changes are needed

Everything worth measuring is already in `PipelineState`:

| Measurement | Source already in state | Finding it addresses |
|---|---|---|
| Evidence IDs resolve | `reasoning_output.patterns[].evidence_review_ids` vs `analysis_results[].review_id` | Tier 1's only live failure (mistyped ID) |
| Frequency recomputed in Python | count negative aspects in `analysis_results` | F2a — deletes the fabricated-statistic class |
| stars-vs-sentiment contradiction rate | `reviews_df` (has `stars`) joined to `analysis_results` | F13a |
| `n` small → low confidence | count of successful `analysis_results` | F1 |
| Report is a subset of upstream | `report_output` vs `reasoning_output` / `strategy_output` | tier1 report checks |
| Recommendations traceable | `strategy_output` vs `reasoning_output` | tier1 strategy checks |

Note on `frequency`: the field **stays in `Pattern`**; what changes is who
writes it — the orchestrator overwrites the LLM's claimed value with the
recomputed one (and flags if they diverge). Nothing downstream
(`strategy_agent.py:85` sort, frontend patterns rendering) notices any
difference. This sidesteps the contract-removal ripple entirely.

## 4. What Option B defers (the honest 20%)

- **F14 / `n_relevant`** — needs `relevant: bool` from the LLM, i.e. a contract
  change. Deferred; `n = successful analyses` is the interim denominator.
- **Confidence intervals** in warnings — computable later inside `measure` with
  zero structural change; deferred only to keep the first PR small.
- **Impact-weighted strategy priority** (the Acme walkthrough) — requires
  forwarding new data into strategy input; deferred (note: the full design
  doesn't specify this data path either, see §6.3).
- **The measure/decide node separation (P1)** — kept as a *function* boundary
  instead of a *node* boundary. Same testability; less graph surgery.

## 5. Costs shared by BOTH options — no hub variant avoids these

**5.1 The SSE emitter must be rewritten.** `main.py:219-233` assumes each agent
runs exactly once (`_AGENT_SEQUENCE.index + 1` guessing) and listens for a node
named `error_handler`. Any graph where an agent can run twice breaks both
assumptions. See Appendix B for the proposed event contract.

**5.2 `recursion_limit` must be raised.** Option B clean run = 9 node visits;
worst case (2 retries × 4 stages) = **25 — exactly LangGraph's default limit**.
Option A's worst case is 36. Either way, callers in `pipeline.py`,
`run_pipeline.py`, and `main.py` must pass `{"recursion_limit": 50}` or a
retry-heavy run crashes with `GraphRecursionError` instead of halting.

**5.3 Retry without feedback is a wasted retry.** All agents run at
`temperature=0`: re-running with an identical prompt reproduces the identical
wrong output, mechanically burning the retry cap. The full design does not
specify a feedback path. Required in both options: the orchestrator writes
*why* into `state["retry_feedback"]` (e.g. `"evidence id SKXs-JiPXpVnAwcXhA5wA
does not exist in the analysis output"`), and the agent node appends it to the
prompt on re-run — the same mechanism `BaseAgent`'s schema self-correction
already uses successfully.

## 6. Defects found in the full design document (apply regardless of option)

**6.1 `skip` semantics are self-contradictory.** §7 of the full design defines
skip as "skip the *next* stage" and §6's pseudocode implements that
(`_next_stage(_next_stage(stage))`), but decision rule 1 issues `skip` when
*the current stage* exhausts retries — which would mark the failed stage
completed and silently drop the stage after it (e.g. strategy fails 3× → report
never runs). Resolution: **drop `skip`**; `proceed_with_warning` + a flag
covers every case more transparently. This also answers the design's own Open
Question 4.

**6.2 `pipeline_status = verdict` breaks existing consumers.** `main.py`
returns HTTP 500 on `"halted"` and the eval harness records
`pipeline_status: complete` into `_summary.json` (quoted in
`EVALUATION_REPORT.md`). Overwriting it with `"proceed"` each cycle silently
breaks both. Resolution: keep `pipeline_status` terminal-only
(`running | complete | halted`), store per-cycle verdicts in a new
`last_verdict` field.

**6.3 The Acme walkthrough promises impact-weighted priority, but no specified
change delivers the data.** Strategy's input remains patterns + root_causes in
both the current code and the design's dependency list; ranking by "reviews
citing wait_time average 4.1 stars" requires forwarding stars-impact data into
strategy input — an unlisted contract change. Either add it to the design or
trim the walkthrough.

## 7. Migration path

```
Option B ──(extract measure into validator_node, add F14/n_relevant, add CI)──► Option A
```

Nothing in Option B is throwaway: `measure`/`decide` become the
validator/decision-rule modules of Option A verbatim. Recommended order:

1. **PR 1 (no graph change):** `measure` + `decide` as a pure module with unit
   tests against the live dumps already in `backend/out/`.
2. **PR 2 (the only structural change):** replace `error_handler` routing with
   the simple hub; rewrite the SSE emitter; raise `recursion_limit`; fix ~4-5
   test files. Requires team agreement first — `graph.py`, `state.py`,
   `orchestrator.py` are protected files.
3. **Later, if the team wants Option A:** extract the node, add
   `relevant: bool`, thresholds from real data.

Independent of both options, **F2b+F3 (forward review text + dates to
reasoning)** remains the single highest-value fabrication fix and can ship any
time.

## 8. Open questions for the team

1. Accept dropping `skip`? (Resolves 6.1; the full design's Q4 already leans
   this way.)
2. Thresholds: propose calibrating `LOW_CONFIDENCE_N` and `contradiction_rate`
   against the 73-review LOVE Grille dumps in `backend/out/` rather than
   debating in the abstract.
3. Is the fully-deterministic orchestrator acceptable for the report narrative,
   or does the team want to keep a logged LLM-escalation branch for the
   "agentic" story? (Option B works with either; the branch is ~15 lines.)
4. Who owns which PR — the hub/graph/SSE work is Member 1/2 territory;
   `retry_feedback` consumption in agent prompts is Member 3.

---

## Appendix A — Draft entry for `docs/DECISIONS.md`

Not added by this document; `DECISIONS.md` is the team's append-only record and
this design is not yet agreed. Paste (and fill in the calibrated thresholds)
when it is.

```markdown
## 2026-07-XX — Orchestrator becomes a simple hub; Tier 1 checks move into the pipeline

**Decision.** The orchestrator runs after every agent stage
(agent → orchestrator → next agent), replacing the failure-only error_handler.
It measures each stage with deterministic checks (evidence-ID resolution,
frequency recomputation, stars-vs-sentiment contradiction rate, sample-size
floor, report subset) — the same logic as `eval/tier1_checks.py`, now enforced
mid-run — and decides `proceed | proceed_with_warning | retry | halt` by hard
rules. No LLM is used for routine decisions. `skip` is removed from the verdict
vocabulary. Retries carry the measured failure into the agent's prompt via
`state["retry_feedback"]`.

Thresholds (calibrated against the 73-review LOVE Grille dumps):
MIN_VIABLE_N = __, LOW_CONFIDENCE_N = __, CONTRADICTION_MAX = __,
FREQUENCY_TOLERANCE = __.

**Why.** The orchestrator was designed as a hub but built as an exception
handler (FINDINGS F7); no stage validated output quality, only technical
failure (F4). The full validator-node redesign (ORCHESTRATOR_DESIGN.md) requires
contract changes and ~8 test-file rewrites; this smaller step delivers the
supervision behaviour with none of the contract ripple, and upgrades to the
full design by extracting `measure()` into a node.

**Consequences.**
- `Pattern.frequency` is recomputed in Python and overwritten by the
  orchestrator; the LLM's claimed value is advisory only.
- New state fields: `flags`, `retry_feedback`, `last_verdict`.
  `pipeline_status` keeps its terminal semantics (`running|complete|halted`).
- Callers pass `recursion_limit=50` (LangGraph default 25 is exactly the
  Option-B worst case).
- The SSE event contract gains `verdict` events and per-stage `attempt`
  numbers (see ORCHESTRATOR_SIMPLE_HUB.md Appendix B).
- `tests/test_graph.py`, `tests/test_orchestrator.py`,
  `tests/test_orchestrator_routing.py`, `tests/mock_agents.py`, and the SSE
  portion of `tests/test_api.py` are rewritten.
```

## Appendix B — SSE event contract (for Member 5)

Current events (`main.py:158-253`): `stage_start`, `stage_end` (with
`duration_ms`, optional `info`), `notice` (only for `error_handler`), `error`,
`done`.

Proposed contract — designed so the frontend change is additive:

| Event | Fields | Change |
|---|---|---|
| `stage_start` | `stage`, **`attempt`** (1-based) | `attempt` added — a retried stage emits `stage_start` again with `attempt: 2` |
| `stage_end` | `stage`, `attempt`, `duration_ms` | `attempt` added |
| `verdict` | `stage`, `verdict` (`proceed \| proceed_with_warning \| retry \| halt`), `flags` (list), `detail` (human-readable reason, present for retry/halt/warning) | **new** — replaces the `error_handler` notice |
| `error` | unchanged | emitted after a `halt` verdict, as today on failure |
| `done` | `report` + **`flags`** (accumulated) | `flags` added so the dashboard can badge low-confidence reports |

Frontend rules:

1. Key timeline entries by `(stage, attempt)`, not by `stage` alone — this is
   the only breaking assumption.
2. `verdict: proceed` may be rendered silently; `proceed_with_warning` shows a
   warning badge with `flags`; `retry` shows a retry marker on the stage;
   `halt` precedes the terminal `error` event.
3. Data-stage events (`search_business`, `load_reviews`, `preprocess`) are
   unchanged.

## Appendix C — Migration checklist by file

### PR 1 — supervision module (no protected files, can start immediately)

| File | Change |
|---|---|
| `backend/app/core/supervision.py` | **new** — `measure(stage, state)`, `decide(stage, facts, retry_counts)`, thresholds as module constants |
| `backend/tests/test_supervision.py` | **new** — unit tests; fixtures from `backend/out/analysis.json` / `reasoning.json` (the run that contains the real mistyped-ID defect — it must be caught) |

### PR 2 — the hub (requires team agreement; protected files)

| File | Change |
|---|---|
| `backend/app/core/graph.py` | replace `error_handler` + per-stage conditional edges with `orchestrator_node` + single router |
| `backend/app/core/orchestrator.py` | `decide_recovery(str, str, int)` → thin wrapper over `supervision.decide(state)`; keep `is_critical` |
| `backend/app/core/state.py` | add `flags: List[str]`, `retry_feedback: Optional[str]`, `last_verdict: Optional[str]` |
| `backend/app/core/nodes.py` | agent nodes read `retry_feedback` and pass it to the agent entry points; clear it after use |
| `backend/app/agents/analysis_agent.py`, `reasoning_agent.py` | accept optional feedback text, append to messages (Member 3) |
| `backend/app/core/pipeline.py`, `backend/run_pipeline.py` | pass `{"recursion_limit": 50}` |
| `backend/app/main.py` | SSE emitter per Appendix B; `recursion_limit` on `graph.stream` |
| `backend/tests/test_graph.py`, `test_orchestrator.py`, `test_orchestrator_routing.py`, `mock_agents.py` | rewrite against hub shape |
| `backend/tests/test_api.py` | update SSE assertions |
| `frontend/src/` (Pipeline Monitor) | key by `(stage, attempt)`; render `verdict` events (Member 5) |

### After PR 2 merges — documentation

| File | Change |
|---|---|
| `docs/DECISIONS.md` | paste Appendix A with calibrated thresholds |
| `README.md` §6, §9 | orchestrator role + error-handling described as hub behaviour |
| `AGENTS.md:48` | fix orchestrator location (`app/agents/` → `app/core/`) — drift caught by F7 |
| `docs/PROGRESS.md` | status update |
