from __future__ import annotations
from pydantic import BaseModel, Field
from flare.models.ingestion import SIGNAL_TYPES

class ExtractedSignal(BaseModel):
    signal_type: str = Field(description=f"one of: {', '.join(SIGNAL_TYPES)}")
    value: dict[str, str] = Field(default_factory=dict) 
    confidence: float = Field(ge=0.0, le=1.0)

class ScribeOutput(BaseModel):
    signals: list[ExtractedSignal] = Field(default_factory=list)

class EvidenceFinding(BaseModel):
    title: str = Field(description="short label, e.g. 'p99 spike on checkout-api'")
    body: str = Field(description="one or two sentences describing the observation")
    confidence: float = Field(ge=0.0, le=1.0)

class ReadAgentOutput(BaseModel):
    findings: list[EvidenceFinding] = Field(default_factory=list)

class HypothesisItem(BaseModel):
    statement: str
    likelihood: float = Field(ge=0.0, le=1.0)
    supports_indices: list[int] = Field(default_factory=list)
    contradicts_indices: list[int] = Field(default_factory=list)

class HypothesisAgentOutput(BaseModel):
    hypotheses: list[HypothesisItem] = Field(default_factory=list)

class SummaryOutput(BaseModel):
    summary: str = Field(description="concise current-state summary, 1-3 sentences")

class CriticOutput(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)

class TriggerOutput(BaseModel):
    decision: str = Field(description="one of: trigger, skip, batch")
    reasons: list[str] = Field(default_factory=list)

class PlannerOutput(BaseModel):
    agents: list[str] = Field(
        default_factory=list,
        description="subset of the offered candidate agents that is worth running",
    )
    focus: str = Field(default="", description="one sentence: what to look at and why")