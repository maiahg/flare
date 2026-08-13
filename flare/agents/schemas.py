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

class VerifierOutput(BaseModel):
    """A verdict on whether gathered evidence bears out one claim."""

    verdict: str = Field(
        description="exactly one of: supported, contradicted, inconclusive"
    )
    rationale: str = Field(
        description="one to three sentences explaining the verdict from the evidence"
    )
    supports_indices: list[int] = Field(
        default_factory=list,
        description="indices from the EVIDENCE list that support the claim",
    )
    contradicts_indices: list[int] = Field(
        default_factory=list,
        description="indices from the EVIDENCE list that contradict the claim",
    )
    confidence: float = Field(
        ge=0.0, le=1.0, default=0.5, description="calibrated confidence in the verdict"
    )

class TriggerOutput(BaseModel):
    decision: str = Field(description="one of: trigger, skip, batch")
    reasons: list[str] = Field(default_factory=list)

class PlannerOutput(BaseModel):
    agents: list[str] = Field(
        default_factory=list,
        description="subset of the offered candidate agents that is worth running",
    )
    focus: str = Field(default="", description="one sentence: what to look at and why")

class CorrectionPlan(BaseModel):
    """Which existing claims a human correction invalidates."""

    invalidates: list[int] = Field(
        default_factory=list,
        description="indices from the numbered CLAIMS list that the correction "
        "contradicts; empty if the correction only adds new information",
    )
    note: str = Field(default="", description="one sentence explaining the change")

class MitigationItem(BaseModel):
    title: str
    description: str = Field(description="what to do, concretely")
    risk: str = Field(description="one of: low, medium, high")
    reversibility: str = Field(description="one of: reversible, partially, irreversible")
    expected_benefit: str = Field(description="what improves if this is applied")

class MitigationOutput(BaseModel):
    options: list[MitigationItem] = Field(default_factory=list)

class GroundedClaim(BaseModel):
    """A sentence plus the evidence indices that support it."""

    text: str = Field(description="one claim, stated plainly")
    evidence_indices: list[int] = Field(
        default_factory=list,
        description="indices from the numbered EVIDENCE list that support this "
        "claim; a claim with no supporting evidence must be omitted entirely",
    )


class PostmortemOutput(BaseModel):
    """The narrative sections of a postmortem draft."""

    impact: list[GroundedClaim] = Field(default_factory=list)
    root_cause: list[GroundedClaim] = Field(default_factory=list)
    contributing_factors: list[GroundedClaim] = Field(default_factory=list)