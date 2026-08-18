"""Simple-hub pipeline graph (docs/ORCHESTRATOR_SIMPLE_HUB.md).

Every agent stage reports to the orchestrator, which measures the output with
deterministic checks (app/core/supervision.py) and decides
``proceed | proceed_with_warning | retry | halt``:

    preprocess -> analysis -> ORCH -> reasoning -> ORCH -> strategy -> ORCH -> report -> ORCH -> END
                                |
                                +- retry -> re-run the stage that just ran (with retry_feedback)
                                +- halt  -> END

The orchestrator holds control at every transition — not only on failure — and
is the single routing node. ``pipeline_status`` keeps its terminal semantics
(``running | complete | halted``); per-cycle verdicts live in ``last_verdict``.

Callers MUST invoke/stream the compiled graph with
``{"recursion_limit": RECURSION_LIMIT}``: the worst case (2 retries on all four
stages) is 25 node visits — exactly LangGraph's default limit.
"""

import os

from langgraph.graph import StateGraph, END

from app.core import supervision
from app.core.state import PipelineState

# Canonical sequential order of the agent nodes (single source of truth in
# supervision.py so measuring and routing can never disagree).
AGENT_SEQUENCE = supervision.AGENT_SEQUENCE

# Worst case: 1 preprocess + 4 stages x (agent + orchestrator) x 3 attempts
# = 25 visits, exactly LangGraph's default recursion limit. Leave headroom.
RECURSION_LIMIT = 50

# ── Observe mode (study Phase A) ─────────────────────────────────────────────
#
# SUPERVISION_MODE=observe turns the orchestrator into a pure instrument: it
# still measures every stage and records every non-proceed verdict into
# ``state["observations"]``, but it does not act on them. Specifically:
#
#   * ``retry`` is downgraded to ``proceed`` — the defective output is kept and
#     the next stage consumes it, which is what an unsupervised pipeline does.
#   * frequency recompute-and-overwrite is NOT applied, so the reasoning output
#     keeps the model's claimed value. Without this the observe arm would be
#     partially supervised and the two arms would not differ only in enforcement.
#   * ``halt`` is still honoured. The only halt reachable in observe mode is
#     ``insufficient_data`` at the analysis stage (retry-cap halts cannot fire
#     because no retry fires), and that is a data precondition rather than a
#     groundedness defect: below MIN_VIABLE_N analysed reviews there is nothing
#     downstream to measure. Sample above that floor to avoid it.
#
# Default is "enforce" — the production behaviour. See docs/paper/CHAPTER_PLAN.md
# section 4 (Evidence Ledger) and scripts/run_study.py.
SUPERVISION_MODE_ENV = "SUPERVISION_MODE"


def observe_mode() -> bool:
    """True when supervision should measure and record but not intervene.

    Read per call rather than at import so a test or a batch runner can flip it
    between runs inside one process.
    """
    return os.getenv(SUPERVISION_MODE_ENV, "enforce").strip().lower() == "observe"


# ── Orchestrator node (measures, then decides — every stage, every run) ──────


def orchestrator_node(state: PipelineState) -> PipelineState:
    stage = supervision.latest_stage(state)
    if stage is None:  # defensive: entry edge goes preprocess -> analysis
        state["last_verdict"] = "proceed"
        return state

    facts = supervision.measure(stage, state)
    decision = supervision.decide(stage, facts, state.get("retry_counts") or {})

    observing = observe_mode()
    if observing:
        # Record EVERY stage, and record the raw measured facts next to the
        # verdict. The verdict alone is not sufficient for the incidence table:
        # decide() returns on the first rule that fires, so a stage carrying
        # both an unresolvable evidence id and a diverging frequency reports
        # only the retry, and the divergence is never counted. ``facts`` has no
        # such precedence -- it is the entire measurement -- so per-check
        # incidence stays computable offline whatever the rule order is. This
        # is the payoff of keeping measure() and decide() separate.
        state.setdefault("observations", []).append({
            "stage": stage,
            "would_be_verdict": decision.verdict,
            "flags": list(decision.flags),
            "retry_feedback": decision.retry_feedback,
            "facts": facts,
        })
        if decision.verdict == "retry":
            decision = supervision.Decision("proceed", list(decision.flags), None)

    flags = state.setdefault("flags", [])
    for flag in decision.flags:
        if flag not in flags:
            flags.append(flag)

    state["last_verdict"] = decision.verdict
    errors = state.setdefault("errors", {})

    if decision.verdict == "retry":
        retry_counts = state.setdefault("retry_counts", {})
        retry_counts[stage] = retry_counts.get(stage, 0) + 1
        state["retry_feedback"] = decision.retry_feedback
        state["failed_agent"] = stage
        errors[stage] = decision.retry_feedback or "quality check failed"
        state["pipeline_status"] = "running"
        return state

    state["retry_feedback"] = None

    if decision.verdict == "halt":
        state["failed_agent"] = stage
        errors[stage] = (
            decision.retry_feedback or "; ".join(decision.flags) or "halted by orchestrator"
        )
        state["pipeline_status"] = "halted"
        return state

    # proceed / proceed_with_warning
    if decision.verdict == "proceed_with_warning" and f"{stage}:gave_up_after_retries" in decision.flags:
        # Non-critical stage abandoned after exhausting retries (the old "skip",
        # now on the record instead of silent).
        skipped = state.setdefault("skipped_agents", [])
        if stage not in skipped:
            skipped.append(stage)
    else:
        errors.pop(stage, None)

    if stage == "reasoning_agent" and not observing:
        # Python is authoritative for frequency (F2a) — patch the claimed
        # values now that this output is final. Skipped in observe mode so the
        # arm stays genuinely unsupervised (see SUPERVISION_MODE notes above).
        supervision.apply_frequency_corrections(state.get("reasoning_output") or {}, facts)

    state["failed_agent"] = None
    state["pipeline_status"] = "complete" if stage == "report_agent" else "running"
    return state


# ── Routing (the orchestrator is the only node that routes) ──────────────────


def route_from_orchestrator(state: PipelineState) -> str:
    verdict = state.get("last_verdict")
    stage = supervision.latest_stage(state)

    if verdict == "halt" or stage is None:
        return "END"
    if verdict == "retry":
        return stage
    nxt = supervision.next_stage(stage)
    return nxt if nxt else "END"


# ── Build the graph ───────────────────────────────────────────────────────────


def build_graph(analysis_node, reasoning_node, strategy_node, report_node, preprocess_node):
    graph = StateGraph(PipelineState)

    graph.add_node("preprocess",      preprocess_node)
    graph.add_node("analysis_agent",  analysis_node)
    graph.add_node("reasoning_agent", reasoning_node)
    graph.add_node("strategy_agent",  strategy_node)
    graph.add_node("report_agent",    report_node)
    graph.add_node("orchestrator",    orchestrator_node)

    graph.set_entry_point("preprocess")
    graph.add_edge("preprocess", "analysis_agent")

    # Every agent reports to the orchestrator; only the orchestrator routes.
    for agent in AGENT_SEQUENCE:
        graph.add_edge(agent, "orchestrator")

    graph.add_conditional_edges("orchestrator", route_from_orchestrator, {
        "analysis_agent":  "analysis_agent",
        "reasoning_agent": "reasoning_agent",
        "strategy_agent":  "strategy_agent",
        "report_agent":    "report_agent",
        "END": END,
    })

    return graph.compile()
