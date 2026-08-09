from __future__ import annotations
from pydantic import BaseModel, Field
from flare.models.ingestion import SIGNAL_TYPES

class ExtractedSignal(BaseModel):
    signal_type: str = Field(description=f"one of: {', '.join(SIGNAL_TYPES)}")
    value: dict[str, str] = Field(default_factory=dict) 
    confidence: float = Field(ge=0.0, le=1.0)


class ScribeOutput(BaseModel):
    signals: list[ExtractedSignal] = Field(default_factory=list)