from __future__ import annotations

from typing import Any

from flare.models.claims import (
    ACTION_ITEM_STATUSES,
    COMMS_STATUSES,
    HYPOTHESIS_STATUSES,
    MITIGATION_STATUSES,
    OPEN_QUESTION_STATUSES,
    ActionItem,
    CommsDraft,
    Decision,
    Evidence,
    Fact,
    Hypothesis,
    MitigationOption,
    OpenQuestion,
    TimelineEntry,
)
from flare.models.provenance import CLAIM_STATUSES

CLAIM_MODELS: tuple[type[Any], ...] = (
    Evidence,
    Fact,
    Hypothesis,
    OpenQuestion,
    Decision,
    ActionItem,
    TimelineEntry,
    MitigationOption,
    CommsDraft,
)

OP_CREATE = "create"
OP_UPDATE = "update"
OP_REJECT = "reject"
OP_STALE = "stale"
OP_SUPERSEDE = "supersede"
OP_RESOLVE = "resolve"

OP_TO_STATUS: dict[str, str] = {
    OP_REJECT: "rejected",
    OP_STALE: "stale",
    OP_SUPERSEDE: "superseded",
    OP_RESOLVE: "resolved",
}

_SPECIALIZED_STATUSES: dict[type[Any], tuple[str, ...]] = {
    Hypothesis: HYPOTHESIS_STATUSES,
    OpenQuestion: OPEN_QUESTION_STATUSES,
    ActionItem: ACTION_ITEM_STATUSES,
    MitigationOption: MITIGATION_STATUSES,
    CommsDraft: COMMS_STATUSES,
}

GLOBAL_IMMUTABLE_FIELDS = frozenset(
    {"id", "incident_id", "created_at", "updated_at", "created_by", "kind", "source"}
)

EVIDENCE_IMMUTABLE_FIELDS = frozenset(
    {"title", "body", "observed_at", "system", "query", "result_ref", "tool_call_id"}
)


def is_claim_model(model: type[Any]) -> bool:
    """True if ``model`` carries the provenance envelope."""
    return model in CLAIM_MODELS


def entity_type(model: type[Any]) -> str:
    """The ``memory_revisions.entity_type`` value for a model (its table name)."""
    return str(model.__tablename__)


def allowed_statuses(model: type[Any]) -> frozenset[str]:
    """Valid ``status`` values: specialized vocabulary ∪ envelope lifecycle."""
    return frozenset(_SPECIALIZED_STATUSES.get(model, ())) | frozenset(CLAIM_STATUSES)


def default_status(model: type[Any]) -> str | None:
    """The model's declared ``status`` default, read from its column."""
    column = model.__table__.c.get("status")
    if column is None or column.server_default is None:
        return None
    arg = column.server_default.arg
    return str(arg)


def immutable_fields(model: type[Any]) -> frozenset[str]:
    """Fields that may not be changed by an update on this model."""
    fields = GLOBAL_IMMUTABLE_FIELDS
    if model is Evidence:
        fields = fields | EVIDENCE_IMMUTABLE_FIELDS
    return fields


def column_names(model: type[Any]) -> frozenset[str]:
    """All mapped column names on a model."""
    return frozenset(c.key for c in model.__table__.columns)