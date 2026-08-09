from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class EvidenceDraft(BaseModel):
    """A cited observation an agent wants to commit as ``evidence``."""

    ref: uuid.UUID = Field(default_factory=uuid.uuid4)
    system: str  
    title: str
    body: str
    query: str  
    result_ref: dict[str, object] = Field(default_factory=dict)
    tool_call_id: uuid.UUID  
    confidence: float = Field(ge=0.0, le=1.0)
    created_by: str  
    observed_at: datetime | None = None
    staleness_at: datetime | None = None


class HypothesisDraft(BaseModel):
    """A candidate explanation referencing the evidence it rests on."""

    ref: uuid.UUID = Field(default_factory=uuid.uuid4)
    statement: str
    likelihood: float = Field(ge=0.0, le=1.0)
    rank: int | None = None
    supports: list[uuid.UUID] = Field(default_factory=list) 
    contradicts: list[uuid.UUID] = Field(default_factory=list)
    created_by: str = "HypothesisAgent"


class CriticVerdict(BaseModel):
    """The safety gate's decision"""

    passed: bool
    reasons: list[str] = Field(default_factory=list)
    downgrade: dict[str, float] = Field(default_factory=dict)