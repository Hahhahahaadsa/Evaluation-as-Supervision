# Orchestrator Redesign — Hub Architecture

**Status:** Proposed. Not yet agreed by the team, not yet implemented.
**Date:** 2026-07-16
**Related:** `docs/FINDINGS_2026-07-16.md` (F1, F2a, F4, F7, F13a, F14)

This document specifies the target design. It is written to be read *before*
any code changes, per `AGENTS.md:77` ("Distinguish agreed target behavior from
current implementation behavior"). Nothing here describes existing behaviour.

---

## 1. Why

The team's agreed design was a transit hub:

```
orchestrator -> analysis -> orchestrator -> reasoning -> orchestrator -> report
```

What was built is a linear chain where the orchestrator is reachable only from a
failure branch (`app/core/graph.py:109-135`). On a successful run it is never
entered. See F7 for the full argument; three properties block it from
supervising as-is:

1. Routing branches only on `status == "error"` (`graph.py:15-35`).
2. `decide_recovery(failed_agent, error_detail, retry_count)` receives no
   `state` — it has nothing to supervise with.
3. Its verdicts (`retry | skip | halt`) have no word for "proceed", because
   proceeding is what happens when it is *not* called.

This design fixes all three.

## 2. Principles

**P1 — Measuring is separate from deciding.** A deterministic validator computes
facts. The orchestrator consumes facts and decides. The validator may not
decide; the orchestrator may not compute (it would guess).

**P2 — Hard rules first, LLM only for genuine ambiguity.** Every routine verdict
is a rule over validator output. This keeps the common path free, deterministic,
and testable — and removes the orchestrator's dependency on the provider it
supervises (F7).

**P3 — Agents keep autonomy over means.** The orchestrator decides *whether* and
*what next*, never *how*. Prompting, schema self-correction, and model fallback
stay inside `BaseAgent` and are not touched.

**P4 — The system must be able to say "I don't know".** Verdicts include
outcomes that let a stage decline rather than fabricate. See §7.

## 3. Graph shape

```
                    ┌──────────────────┐
          ┌────────►│   ORCHESTRATOR   │──── halt ────► END
          │         │   (decides)      │
          │         └────────┬─────────┘
          │                  │ proceed / retry
          │                  ▼
   ┌──────┴──────┐    ┌─────────────┐
   │  VALIDATOR  │◄───│    AGENT    │
   │  (measures) │    │  analysis / │
   └─────────────┘    │  reasoning /│
                      │  strategy / │
                      │  report     │
                      └─────────────┘
```

One cycle = **agent runs -> validator measures -> orchestrator decides**.
Four agents = four cycles.

```python
graph.add_node("orchestrator", orchestrator_node)
graph.add_node("validator",    validator_node)
graph.add_node("analysis_agent",  analysis_node)
graph.add_node("reasoning_agent", reasoning_node)
graph.add_node("strategy_agent",  strategy_node)
graph.add_node("report_agent",    report_node)

graph.set_entry_point("orchestrator")

# every agent reports to the validator, which reports to the orchestrator
for agent in ("analysis_agent", "reasoning_agent", "strategy_agent", "report_agent"):
    graph.add_edge(agent, "validator")
graph.add_edge("validator", "orchestrator")

# the orchestrator is the only node that routes
graph.add_conditional_edges("orchestrator", route_from_orchestrator, {
    "analysis_agent":  "analysis_agent",
    "reasoning_agent": "reasoning_agent",
    "strategy_agent":  "strategy_agent",
    "report_agent":    "report_agent",
    "END": END,
})
```

Note the orchestrator is the **entry point**: it holds control from the start,
not from the first failure.

## 4. State additions

```python
class PipelineState(TypedDict):
    ...  # existing fields unchanged

    current_stage:    Optional[str]   # set by orchestrator before dispatch;
                                      # read by validator to know what to check
    completed_stages: List[str]       # how the orchestrator knows where it is
    validation:       Optional[Dict]  # latest validator report
    flags:            List[str]       # e.g. "low_confidence:n=13"
    n_relevant:       Optional[int]   # true denominator (F1, F14)
```

`current_stage` is what lets a single validator node serve all four agents:
the orchestrator sets it when dispatching, the validator reads it to select
which checks to run.

## 5. Validator

Deterministic. No LLM. Most of the logic already exists in
`eval/tier1_checks.py` — this moves it from "scored offline afterwards" to
"measured in the pipeline".

```python
def validator_node(state: PipelineState) -> PipelineState:
    stage = state["current_stage"]
    state["validation"] = _CHECKS[stage](state)
    return state
```

| Stage | Measures | Source |
|---|---|---|
| analysis | `n_loaded`, `n_success`, `n_relevant`, `contradiction_rate` (`stars` vs `sentiment`) | F13a, F14 |
| reasoning | `frequency` **computed in Python**, confidence interval, evidence IDs resolve, aspect alignment | F1, F2a, `tier1_checks.py:105-195` |
| strategy | each `recommendation.issue` traces to a pattern/root cause; priority order vs impact | `tier1_checks.py:201-270` |
| report | `root_causes`/`recommendations` are subsets of upstream; `business_name`/`sample_size` match trusted state | `tier1_checks.py:276-336` |

**`frequency` is computed here, not claimed by the LLM** (F2a). This deletes a
hallucination class and is what makes the confidence interval possible: Python
knows `n`, the model does not.

## 6. Orchestrator

```python
def decide(self, state: PipelineState) -> str:
    """Returns: proceed | proceed_with_warning | retry | skip | halt"""
```

Replaces `decide_recovery(failed_agent, error_detail, retry_count)`. The old
signature cannot carry a supervision decision (F7).

```python
def orchestrator_node(state: PipelineState) -> PipelineState:
    stage = state.get("current_stage")

    if stage is None:                       # first entry — nothing has run yet
        state["current_stage"] = "analysis_agent"
        return state

    verdict = orchestrator.decide(state)

    if verdict == "retry":
        state["retry_counts"][stage] = state["retry_counts"].get(stage, 0) + 1
    else:
        state.setdefault("completed_stages", []).append(stage)
        if verdict == "proceed_with_warning":
            state.setdefault("flags", []).extend(orchestrator.warnings(state))
        state["current_stage"] = _next_stage(stage) if verdict != "skip" \
                                 else _next_stage(_next_stage(stage))

    state["pipeline_status"] = verdict
    return state
```

### Decision rules

Evaluated top to bottom. **The retry cap is checked first, before every other
rule** — see §9 on loops.

| Stage | Condition | Verdict |
|---|---|---|
| *any* | `retry_counts[stage] >= MAX_RECOVERY_RETRIES` | `halt` if critical else `skip` |
| analysis | `n_relevant < MIN_VIABLE_N` (proposed: 5) | `halt` — "insufficient data" |
| analysis | `contradiction_rate > 0.20` | `retry` — model is misfiring |
| analysis | `n_success / n_loaded <= 0.50` | `halt` (critical) |
| analysis | `n_relevant < LOW_CONFIDENCE_N` (proposed: 30) | `proceed_with_warning` |
| reasoning | evidence IDs do not resolve | `retry` — fabricated citations |
| reasoning | aspect alignment fails | `retry` |
| reasoning | confidence interval wider than `CI_MAX_WIDTH` | `proceed_with_warning` |
| strategy | recommendations untraceable | `retry` |
| report | not a subset of upstream, or metadata mismatch | `retry` |
| *any* | none of the above | `proceed` |
| *any* | error not covered by any rule | escalate to LLM (P2) |

Thresholds are proposals, not agreed values. See §11.

## 7. Verdicts

| Verdict | Meaning | New? |
|---|---|---|
| `proceed` | continue — now an explicit decision on the record | **yes** |
| `proceed_with_warning` | continue, but flag the stage; the report **must** disclose the flag | **yes** |
| `retry` | re-run the stage that just ran | no |
| `skip` | skip the next stage (non-critical only) | no |
| `halt` | stop; no defensible report is possible | no |

`proceed_with_warning` is what makes F1 actionable rather than merely reported:
n=13 continues, but the report is obliged to say so.

## 8. Walkthroughs

### Median business (15 reviews)

```
orchestrator  -> dispatch analysis
analysis      -> 15 analysed
validator     -> n_relevant=13, contradiction=0.00
orchestrator  -> proceed_with_warning   flags=["low_confidence:n=13"]
reasoning     -> pattern "long wait"
validator     -> frequency=0.38 (Python), CI=[18%, 62%]
orchestrator  -> proceed_with_warning   flags+=["ci_too_wide:wait_time"]
strategy      -> recommendations traceable
orchestrator  -> proceed
report        -> MUST state: "38% (CI 18-62%, n=13) - insufficient evidence"
```

Today, the same data yields `frequency: 0.38`, `confidence: "high"`, no warning.

### Large business (Acme Oyster House, 7,673 reviews)

```
analysis      -> 100 sampled (cap active), 96 relevant
validator     -> n_relevant=96, contradiction=0.02
orchestrator  -> proceed (no flags)
reasoning     -> pattern "long wait", 40/96
validator     -> frequency=0.42, CI=[32%, 52%]
                 impact: reviews citing wait_time average 4.1 stars
orchestrator  -> proceed
strategy      -> priority ordered by impact, not frequency
report        -> "42% cite waiting, but they still rate 4.1 - not the problem to fix"
```

The impact measure is why this matters: Acme holds a stable ~4.1-4.2 rating
across 17 years while being famous for queues. Ranking `wait_time` first by
frequency would send the owner to fix something customers demonstrably accept.

## 9. Loop safety — required, not optional

Today `error_handler` is reachable only from a failure branch, so loops are
naturally bounded. Once the orchestrator sits between every stage, a mis-scoped
`retry` can cycle forever. Two mitigations, both mandatory:

**The retry cap is the first rule.** `retry_counts[stage] >= MAX_RECOVERY_RETRIES`
is evaluated before any other condition and before any LLM escalation.

**Raise LangGraph's recursion limit.** This will otherwise break on the first
retry. One clean cycle costs 3 node visits (orchestrator -> agent -> validator),
so a clean run is ~12-13. With 2 retries per stage the worst case is:

```
4 stages x 3 visits x 3 attempts = 36 node visits
```

LangGraph's default `recursion_limit` is **25**. A pipeline that retries twice on
two stages will hit `GraphRecursionError` before finishing — and it will surface
as a crash, not as a halt verdict. Callers must pass an explicit limit:

```python
graph.invoke(initial_state(...), {"recursion_limit": 50})
```

Applies to `app/core/pipeline.py:run_pipeline`, `build_pipeline` callers, and the
SSE `graph.stream(...)` call in `app/main.py:219`.

## 10. Cost

**LLM calls per run: unchanged — still 13.** The validator is pandas. The
orchestrator is rules over validator output. LLM escalation happens only for
cases no rule covers (P2), which is where deliberation is actually warranted —
unlike today, where an LLM is billed to decide something `if` statements largely
already determine (F7).

Side benefit: the common path no longer touches the provider, so the supervisor
stops depending on the component it supervises.

## 11. Open questions for the team

1. **Thresholds.** `MIN_VIABLE_N=5`, `LOW_CONFIDENCE_N=30`, `CI_MAX_WIDTH`,
   `contradiction_rate > 0.20` are all placeholders. They should be argued, and
   recorded in `docs/DECISIONS.md`.
2. **Halting on small samples.** Should `n_relevant < 5` halt, or proceed with a
   maximal warning? Halting is more honest; it also means the system refuses
   service on a meaningful share of businesses (p10 = 6 reviews).
3. **Is the LLM escalation path worth keeping at all?** If hard rules cover
   ~95% of cases, the remaining LLM call may be ceremony. Dropping it makes the
   orchestrator fully deterministic — cheaper and more testable, but harder to
   present as an "agent". This is a real trade-off; the team should make it
   deliberately rather than by default.
4. **Does `skip` still make sense?** With `proceed_with_warning` available,
   skipping a non-critical stage silently may be strictly worse than running it
   and flagging the result.

## 12. Dependencies and order

This design is only as good as what the validator can measure. Building the hub
first means the orchestrator is consulted at all four stages and receives an
LLM-guessed `frequency` every time — it would make decisions more regularly on
the same fabricated data.

Required first:

1. **F2a** — move `frequency` out of the LLM contract; compute it in Python with `n`.
2. **F2b + F3** — forward `text` and `date` to reasoning (same code site).
3. **F14** — add `relevant: bool` to `AnalysisOutput`, so `n_relevant` exists.
4. **F13a** — `stars` vs `sentiment` contradiction check.
5. **F4** — the validator node itself.
6. **This document.**

## 13. Migration impact

**Tests will break.** `tests/test_graph.py`, `tests/test_orchestrator.py`, and
`tests/test_orchestrator_routing.py` assert against the current graph shape and
the `decide_recovery` signature. The 71 offline tests are this project's most
valuable asset — budget for rewriting a portion of them, and do not let it be a
surprise.

**Contract changes** (`frequency` removed from `ReasoningOutput`, `relevant`
added to `AnalysisOutput`) require entries in `docs/DECISIONS.md`.

**Documentation.** `README.md:159` and `:261` currently describe the
error-handler behaviour as though it were the design; `AGENTS.md:48` places the
orchestrator in `backend/app/agents/` (it is in `app/core/`). Both need updating
— and per F7, the hub design should be recorded *before* the code lands, so the
gap is on the record either way.

---

## Appendix — draft entry for `docs/DECISIONS.md`

Not added by this document; `DECISIONS.md` is the team's append-only record and
this design is not yet agreed. Paste when it is.

```markdown
## 2026-07-16 - Orchestrator becomes a hub; measuring split from deciding

**Decision.** The Orchestrator holds control at every stage transition
(orchestrator -> agent -> validator -> orchestrator), restoring the originally
agreed hub design. A new deterministic validator node measures each stage; the
Orchestrator decides on those measurements. Verdicts extend to
`proceed | proceed_with_warning | retry | skip | halt`.

**Why.** The implementation had drifted to a linear chain with the Orchestrator
reachable only on failure, and the documentation had been back-fitted to the
code until the intended design left the written record (FINDINGS_2026-07-16 F7).
Separately, no stage validated output quality — only technical failure (F4).

**Consequences.**
- `Pattern.frequency` is computed in Python, not produced by the LLM (F2a).
- `AnalysisOutput` gains `relevant: bool` (F14); `n_relevant` becomes the
  denominator for all reported statistics (F1).
- `decide_recovery(str, str, int)` is replaced by `decide(state)`.
- Callers must pass `recursion_limit=50`; LangGraph's default of 25 is
  insufficient once the orchestrator sits between every stage.
- Graph and orchestrator tests require rewriting.
```
