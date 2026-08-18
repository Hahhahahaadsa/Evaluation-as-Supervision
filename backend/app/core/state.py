from typing import TypedDict, Optional, List, Dict, Any

class PipelineState(TypedDict):
    # Input
    business_name: str
    business_id: Optional[str]

    # Data layer (Member 2 fills these)
    reviews_df: Optional[Any]           # pandas DataFrame

    # Agent outputs (Members 3 & 4 fill these)
    analysis_results: Optional[List[Dict]]   # list of per-review JSON
    reasoning_output: Optional[Dict]
    strategy_output:  Optional[Dict]
    report_output:    Optional[Dict]

    # Error handling (YOU manage these)
    retry_counts:    Dict[str, int]     # { "analysis": 0, "reasoning": 0, ... }
    skipped_agents:  List[str]
    errors:          Dict[str, str]     # { "analysis": "error detail" }

    # Pipeline control (YOU manage these)
    pipeline_status:  str               # "running" | "halted" | "complete" (terminal semantics only)
    failed_agent:     Optional[str]     # set when an agent returns error status

    # Simple-hub supervision (see docs/ORCHESTRATOR_SIMPLE_HUB.md)
    flags:            List[str]         # e.g. "low_confidence:n=13", "frequency_corrected:..."
    retry_feedback:   Optional[str]     # why the orchestrator ordered a retry; consumed by the re-run
    last_verdict:     Optional[str]     # proceed | proceed_with_warning | retry | halt

    # Observe mode (study Phase A, see scripts/run_study.py). Every non-proceed
    # verdict is appended here whether or not it was acted on, so a single
    # observe run yields the full defect record for an UNSUPERVISED pipeline.
    observations:     List[Dict]