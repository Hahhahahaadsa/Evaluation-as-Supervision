# tests/test_state.py
from app.core.state import PipelineState

def test_state_initialises():
    state: PipelineState = {
        "business_name": "McDonald's",
        "business_id": None,
        "reviews_df": None,
        "analysis_results": None,
        "reasoning_output": None,
        "strategy_output": None,
        "report_output": None,
        "retry_counts": {},
        "skipped_agents": [],
        "errors": {},
        "pipeline_status": "running",
        "failed_agent": None,
        "flags": [],
        "retry_feedback": None,
        "last_verdict": None,
    }
    assert state["business_name"] == "McDonald's"
    assert state["pipeline_status"] == "running"
    assert state["flags"] == []