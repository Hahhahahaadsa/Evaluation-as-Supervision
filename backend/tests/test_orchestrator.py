import pytest
# tests/test_orchestrator.py
from app.core.orchestrator import OrchestratorAgent

orchestrator = OrchestratorAgent()

@pytest.mark.integration
def test_decide_retry():
    decision = orchestrator.decide_recovery(
        failed_agent="analysis",
        error_detail="Missing required field: sentiment",
        retry_count=0
    )
    assert decision in ("retry", "skip", "halt")

def test_decide_halt_after_max_retries():
    decision = orchestrator.decide_recovery(
        failed_agent="analysis",
        error_detail="Persistent JSON parse failure",
        retry_count=2
    )
    assert decision == "halt"  # hard rule — critical agent, retries exhausted
