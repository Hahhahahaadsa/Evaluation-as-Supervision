import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.core import llm_config, supervision

load_dotenv()


class OrchestratorAgent:
    # Critical agents are stored WITHOUT the "_agent" suffix. Matching is
    # suffix-insensitive, so "analysis", "analysis_agent" and "ANALYSIS"
    # all resolve to the same agent. If a critical agent fails it must halt
    # the pipeline rather than be skipped.
    CRITICAL_AGENTS = {"analysis", "reasoning"}
    MAX_RECOVERY_RETRIES = 2

    def __init__(self):
        # LLM client is created lazily so importing/instantiating the
        # orchestrator (e.g. when building the graph) does not require
        # credentials. It is only built when an LLM decision is needed.
        self._llm = None

    def _get_llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=llm_config.primary_model(),
                base_url=llm_config.base_url() or None,
                api_key=llm_config.api_key(),
                temperature=0,
            )
        return self._llm

    @staticmethod
    def _normalize(agent: str) -> str:
        return (agent or "").strip().lower().removesuffix("_agent")

    def is_critical(self, agent: str) -> bool:
        return self._normalize(agent) in self.CRITICAL_AGENTS

    def decide(self, state: dict) -> supervision.Decision:
        """Simple-hub supervision: measure the stage that just ran, then apply
        the deterministic decision rules (docs/ORCHESTRATOR_SIMPLE_HUB.md §2).

        Runs after EVERY stage, not only on failure. No LLM involved — the
        common path must not depend on the provider it supervises.
        """
        stage = supervision.latest_stage(state)
        if stage is None:  # nothing has run yet — nothing to judge
            return supervision.Decision("proceed")
        facts = supervision.measure(stage, state)
        return supervision.decide(stage, facts, state.get("retry_counts") or {})

    def decide_recovery(self, failed_agent: str, error_detail: str, retry_count: int) -> str:
        """Choose a recovery strategy: retry | skip | halt."""
        critical = self.is_critical(failed_agent)

        # Hard rules first — no need to call the LLM.
        if retry_count >= self.MAX_RECOVERY_RETRIES:
            return "halt" if critical else "skip"

        prompt = f"""
You are supervising an AI pipeline that analyses restaurant reviews.
An agent has failed. Decide the recovery strategy.

Failed agent: {failed_agent}
Error: {error_detail}
Retries already attempted: {retry_count}
Is this a critical agent (failure = no meaningful output): {critical}

Choose exactly ONE:
- retry  : error looks recoverable, retry count is low
- skip   : agent is non-critical, pipeline can continue with partial data
- halt   : critical failure, cannot produce a useful report

Respond with ONLY one word: retry, skip, or halt
"""
        try:
            response = self._get_llm().invoke([HumanMessage(content=prompt)])
        except Exception:
            return "retry"
        decision = response.content.strip().lower()

        # Safety fallback if the LLM returns something unexpected.
        if decision not in ("retry", "skip", "halt"):
            return "retry"
        return decision
