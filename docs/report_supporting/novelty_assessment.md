# Novelty Assessment — COS30018 Group 4.1
**Assessor:** Orchestrator (Claude Fable 5), 2026-07-22
**Basis:** README.md, PROJECT_AUDIT.md, docs/EVALUATION_REPORT.md, docs/ORCHESTRATOR_SIMPLE_HUB.md, backend/app/core/graph.py + supervision.py (verified implemented)

## What is genuinely distinctive (claimable novelty)

### N1. Evaluation checks promoted into runtime supervision ("eval-as-orchestration")
The team's strongest and most defensible novelty claim. The Tier 1 deterministic
groundedness checks (evidence-ID resolution, frequency recomputation,
stars-vs-sentiment contradiction rate, report-subset consistency) were first
built as an *offline* evaluation harness, then the same measurement logic was
promoted into the *runtime* orchestrator (`app/core/supervision.py:measure`),
enforced after every agent stage. Most course/industry systems evaluate after
the fact; here the evaluation IS the supervisor. The insight that "each stage is
derivable from the previous, so correctness reduces to consistency checks that
need no ground truth" (EVALUATION_REPORT §3) makes this possible without labels
at runtime. Literature analog: guardrails/verifier patterns — but the explicit
eval-tier→orchestrator promotion with shared code (`AGENT_SEQUENCE = supervision.AGENT_SEQUENCE`
so "measuring and routing can never disagree") is the team's own construction.

### N2. Fully deterministic (LLM-free) supervisor over an LLM multi-agent system
The canonical LangGraph "supervisor" pattern routes with an LLM. This system's
hub routes with hard rules over measured facts: verdicts
proceed / proceed_with_warning / retry / halt are decided by pure functions —
auditable, reproducible, zero marginal cost, and unit-testable against recorded
run dumps. The team explicitly considered and rejected an LLM-escalation branch
(ORCHESTRATOR_SIMPLE_HUB §8 Q3). Position this as a considered design argument:
determinism where determinism suffices; LLMs only where judgment is required.

### N3. Fabricated-statistic elimination by recompute-and-overwrite
`Pattern.frequency` remains in the LLM contract, but the orchestrator recomputes
it in Python from the analysis results and OVERWRITES the LLM's claimed value,
flagging divergence (supervision.apply_frequency_corrections, wired in
graph.py:87). LLM numeric claims are demoted to advisory. This is a concrete,
implemented anti-hallucination mechanism for quantitative claims — narrower and
more enforceable than generic "grounding" prompts.

### N4. One feedback mechanism, two layers of correction
The schema self-correction loop (BaseAgent: Pydantic error → correction prompt,
max 2 retries) and the semantic supervision loop (hub: measured groundedness
failure → `state["retry_feedback"]` appended to the re-run prompt) reuse the
same mechanism at two different layers — syntactic validity and semantic
grounding. Grounded in Self-Refine/Reflexion-style verbal feedback, but the
feedback here is deterministic error text (a Pydantic trace or a measured fact
like "evidence id X does not exist"), not LLM self-critique. The team also
identified that retry-without-feedback at temperature=0 is mechanically wasted
(identical prompt → identical wrong output) — a small but sharp observation
worth stating in the report.

### N5. Honesty enforced by contract, not by convention
`limitations` is a REQUIRED field of `ReportOutput` — the report schema itself
forces the system to state its bounds. Combined with: the 100-review sampling
cap stated as a non-goal ("must never claim to analyse every Yelp review"),
trusted-state overwrite of report `business_name`/`sample_size` (model-claimed
metadata replaced from validated state), and per-run `run_config` provenance in
every eval dump. As a cluster this amounts to a design stance: every claim the
system makes is either machine-verified, recomputed, or explicitly bounded.

### N6. Four-tier evaluation as a composed methodology
Tier 1 (deterministic consistency, no labels), Tier 1b (reproducibility,
latency/cost, 6 failure-injection scenarios), Tier 2 (73-review full-business
human gold set — deliberately labelling the WHOLE business to kill
cherry-picking concerns), Tier 3 (independent stronger judge model to avoid
self-preference bias). Each tier individually has literature precedent; the
composition, and the "healthy harness catches exactly one honest error"
argument (24/25 with a real caught defect beats a suspicious 25/25), are the
team's own methodological contributions.

## What is NOT novel (do not overclaim)
- Multi-agent role decomposition (analysis→reasoning→strategy→report) — standard
  pipeline specialization (MetaGPT/AutoGen lineage).
- The 7 aspect categories / ABSA itself — SemEval-2014 Task 4 territory.
- LLM-as-judge with rubrics — established (MT-Bench, G-Eval); the independent-
  judge choice is good practice, not novelty.
- Pydantic-validated structured output — widespread engineering practice.
- LangGraph, SSE progress streaming, FastAPI/React — commodity infrastructure.

## How to phrase it in the report
Frame as "distinctive engineering contributions of this project" rather than
"research novelty" — appropriate for a coursework report. Lead with N1+N2+N3
(they form one coherent story: a deterministic, evaluation-derived supervisor
that verifies and corrects LLM claims mid-run), support with N4/N5, and present
N6 in the evaluation section. Cross-check against the research-grounding
agent's GAPS section before finalizing.
