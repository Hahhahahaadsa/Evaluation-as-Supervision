from typing import Any, Literal

from pydantic import BaseModel, Field


AspectCategory = Literal[
    "food_quality",
    "staff_attitude",
    "pricing",
    "wait_time",
    "ambience",
    "cleanliness",
    "other",
]


class ReviewRecord(BaseModel):
    review_id: str
    business_id: str
    stars: int
    text: str
    date: str


class AgentError(BaseModel):
    status: Literal["error"] = "error"
    agent: str
    error_type: str
    error_detail: str
    retry_count: int
    recoverable: bool


class AspectLabel(BaseModel):
    category: AspectCategory
    label: Literal["positive", "negative", "neutral"]


class AnalysisOutput(BaseModel):
    review_id: str
    sentiment: Literal["positive", "negative", "neutral", "mixed"]
    aspects: list[AspectLabel]
    status: Literal["success", "error"]
    error_detail: str | None = None


class AnalysisBatchOutput(BaseModel):
    """One LLM call analyses several reviews at once to stay within rate limits."""

    analyses: list[AnalysisOutput]


class Pattern(BaseModel):
    description: str
    aspect: AspectCategory
    frequency: float = Field(ge=0.0, le=1.0)
    evidence_review_ids: list[str] = Field(min_length=1)


class RootCause(BaseModel):
    pattern: str
    cause: str
    confidence: Literal["low", "medium", "high"]


class ReasoningOutput(BaseModel):
    patterns: list[Pattern]
    root_causes: list[RootCause]
    status: Literal["success", "error"]
    error_detail: str | None = None


class StrategicAgentInput(BaseModel):
    patterns: list[Pattern] = Field(default_factory=list)
    root_causes: list[RootCause] = Field(default_factory=list)


class Recommendation(BaseModel):
    priority: int = Field(ge=1)
    issue: str
    action: str
    category: str
    expected_impact: str


class StrategyOutput(BaseModel):
    recommendations: list[Recommendation]
    status: Literal["success", "error"]
    error_detail: str | None = None


class ReportGeneratorInput(BaseModel):
    business_name: str
    sample_size: int = Field(ge=0)
    analysis_summary: dict[str, Any] = Field(default_factory=dict)
    reasoning_summary: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[Recommendation] = Field(default_factory=list)


class ReportOutput(BaseModel):
    title: str = "Restaurant Review Analysis Report"
    business_name: str
    sample_size: int = Field(ge=0)
    executive_summary: str
    key_findings: list[str] = Field(default_factory=list)
    root_causes: list[RootCause] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    status: Literal["success", "error"]
    error_detail: str | None = None
