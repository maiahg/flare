from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    """Base for schemas read directly off SQLAlchemy rows."""

    model_config = ConfigDict(from_attributes=True)

class ProvenanceEnvelope(ORMModel):
    """The fields every claim carries."""

    id: uuid.UUID
    incident_id: uuid.UUID
    kind: str | None = None
    confidence: float | None = None
    source: dict[str, Any] | None = None
    created_by: str | None = None
    status: str | None = None
    last_verified_at: datetime | None = None
    superseded_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

class IncidentSummaryCounts(BaseModel):
    """Per-entity counts shown on the overview header."""

    facts: int = 0
    evidence: int = 0
    hypotheses: int = 0
    open_questions: int = 0
    decisions: int = 0
    action_items: int = 0
    timeline_entries: int = 0
    mitigation_options: int = 0

class IncidentRead(ORMModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    slack_channel_id: str | None = None
    title: str
    description: str | None = None
    status: str
    severity: str | None = None
    mode: str
    started_at: datetime | None = None
    detected_at: datetime | None = None
    mitigated_at: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    source: dict[str, Any] | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

class SummaryRead(ORMModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    scope: str
    body: str | None = None
    version: int
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

class IncidentDetail(IncidentRead):
    """Overview payload: the incident, its current summary, and counts."""

    summary: SummaryRead | None = None
    counts: IncidentSummaryCounts

class FactRead(ProvenanceEnvelope):
    statement: str | None = None

class EvidenceRead(ProvenanceEnvelope):
    title: str | None = None
    body: str | None = None
    observed_at: datetime | None = None
    system: str | None = None
    query: str | None = None
    result_ref: dict[str, Any] | None = None
    tool_call_id: uuid.UUID | None = None
    staleness_at: datetime | None = None

class HypothesisRead(ProvenanceEnvelope):
    statement: str | None = None
    rank: int | None = None
    likelihood: float | None = None
    supporting_evidence: list[EvidenceRead] = Field(default_factory=list)
    contradicting_evidence: list[EvidenceRead] = Field(default_factory=list)

class OpenQuestionRead(ProvenanceEnvelope):
    question: str | None = None
    owner_user_id: uuid.UUID | None = None
    answer: str | None = None

class DecisionRead(ProvenanceEnvelope):
    statement: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    rationale: str | None = None

class ActionItemRead(ProvenanceEnvelope):
    description: str | None = None
    owner_user_id: uuid.UUID | None = None
    due_at: datetime | None = None

class TimelineEntryRead(ProvenanceEnvelope):
    occurred_at: datetime | None = None
    entry_type: str | None = None
    description: str | None = None

class MitigationOptionRead(ProvenanceEnvelope):
    title: str | None = None
    description: str | None = None
    risk: str | None = None
    reversibility: str | None = None
    expected_benefit: str | None = None
    approval_required: bool | None = None

class CommsDraftRead(ProvenanceEnvelope):
    audience: str | None = None
    body: str | None = None
    version: int | None = None

class PostmortemDraftRead(ORMModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    sections: dict[str, Any] | None = None
    follow_ups: dict[str, Any] | list[Any] | None = None
    version: int
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

class ToolCallRead(ORMModel):
    id: uuid.UUID
    run_id: uuid.UUID | None = None
    agent_trace_id: uuid.UUID | None = None
    tool_name: str
    system: str | None = None
    args: dict[str, Any] | None = None
    args_hash: str | None = None
    read_only: bool | None = None
    status: str | None = None
    latency_ms: int | None = None
    result_ref: dict[str, Any] | None = None
    redactions: dict[str, Any] | list[Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    created_at: datetime

class AgentTraceRead(ORMModel):
    id: uuid.UUID
    run_id: uuid.UUID
    agent_name: str
    seq: int | None = None
    status: str | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    reasoning_summary: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    tokens: dict[str, Any] | None = None
    model_name: str | None = None
    provider_request_id: str | None = None
    error: str | None = None
    created_at: datetime
    tool_calls: list[ToolCallRead] = Field(default_factory=list)

class RunRead(ORMModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    run_type: str
    trigger: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    token_in: int | None = None
    token_out: int | None = None
    provider_request_id: str | None = None
    limitations: list[str] | None = None
    summary: str | None = None
    created_by: str | None = None
    created_at: datetime

class RunDetail(RunRead):
    """A run plus its agent traces and the tool calls beneath them."""

    agent_traces: list[AgentTraceRead] = Field(default_factory=list)

class TriggerRead(ORMModel):
    """One trigger decision, with the reasons that produced it."""

    id: uuid.UUID
    incident_id: uuid.UUID
    message_id: uuid.UUID | None = None
    decision: str | None = None
    score: float | None = None
    reasons: dict[str, Any] | None = None
    run_id: uuid.UUID | None = None
    created_at: datetime

class RevisionRead(ORMModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    op: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    diff: dict[str, Any] | None = None
    actor: str | None = None
    run_id: uuid.UUID | None = None
    reason: str | None = None
    created_at: datetime

class ApprovalRead(ORMModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    subject_type: str | None = None
    subject_id: uuid.UUID | None = None
    requested_by: str | None = None
    requested_at: datetime | None = None
    status: str
    decided_by: str | None = None
    decided_at: datetime | None = None
    note: str | None = None
    created_at: datetime

class WriteModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class IncidentCreate(WriteModel):
    title: str
    description: str | None = None
    channel_id: str | None = None
    alert_payload: dict[str, Any] | None = None
    workspace_id: uuid.UUID | None = None

class ModeUpdate(WriteModel):
    mode: str

class InvestigateRequest(WriteModel):
    target: str | None = None
    since: str | None = None
    focus: str | None = None

class FactPatch(WriteModel):
    statement: str | None = None
    status: str | None = None

class HypothesisPatch(WriteModel):
    status: str | None = None
    rank: int | None = None

class EvidencePatch(WriteModel):
    """Evidence accepts exactly one edit: marking it stale."""

    status: str

class QuestionPatch(WriteModel):
    owner_user_id: uuid.UUID | None = None
    status: str | None = None
    answer: str | None = None

class ActionItemCreate(WriteModel):
    description: str
    owner_user_id: uuid.UUID | None = None
    due_at: datetime | None = None

class ActionItemPatch(WriteModel):
    status: str | None = None
    owner_user_id: uuid.UUID | None = None

class CommsGenerate(WriteModel):
    audience: str

class CommsDraftPatch(WriteModel):
    body: str

class CorrectionCreate(WriteModel):
    correction_text: str
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None

class CorrectionResult(BaseModel):
    """What the correction recorded, and what it invalidated."""

    fact: FactRead
    invalidated: list[dict[str, str]] = Field(default_factory=list)
    note: str = ""

class ApprovalDecision(WriteModel):
    decision: str
    note: str | None = None

class RunAccepted(BaseModel):
    """A manual run was queued (it executes on the worker, not in-request)."""

    status: str = "queued"
    incident_id: uuid.UUID
    target: str | None = None
    focus: str | None = None


class AgentTokenUsage(BaseModel):
    """One agent's share of an incident's tokens."""

    agent_name: str
    calls: int
    tokens_in: int
    tokens_out: int


class RunTokenUsage(BaseModel):
    """Per-run usage — the row the run detail shows."""

    run_id: uuid.UUID
    run_type: str | None = None
    status: str | None = None
    created_at: datetime
    tokens_in: int
    tokens_out: int

    @property
    def total(self) -> int:
        return self.tokens_in + self.tokens_out


class IncidentUsage(BaseModel):
    """Token spend for an incident against its budget"""

    incident_id: uuid.UUID
    tokens_in: int
    tokens_out: int
    total: int
    runs: int
    budget: int
    remaining: int
    near_cap: bool
    exhausted: bool
    by_run: list[RunTokenUsage] = Field(default_factory=list)
    by_agent: list[AgentTokenUsage] = Field(default_factory=list)


class ErasureRequest(WriteModel):
    """``DELETE /incidents/{id}`` body — deletion needs a stated reason."""

    detail: str
    reason: str = "request"


class ErasureReceiptRead(BaseModel):
    """Proof of what a deletion removed."""

    incident_id: uuid.UUID
    tombstone_id: uuid.UUID
    row_counts: dict[str, int] = Field(default_factory=dict)
    export_ref: str | None = None