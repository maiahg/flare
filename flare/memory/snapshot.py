from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

#: Columns never recorded in a snapshot
EXCLUDED_FIELDS = frozenset({"embedding", "updated_at"})


def jsonable(value: Any) -> Any:
    """Coerce a column value into something JSONB can store."""
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return str(value)


def snapshot(entity: Any) -> dict[str, Any]:
    """A JSON-safe dict of an entity's column values."""
    columns = type(entity).__table__.columns
    return {
        column.key: jsonable(getattr(entity, column.key))
        for column in columns
        if column.key not in EXCLUDED_FIELDS
    }


def diff(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> dict[str, dict[str, Any]]:
    """Field-level changes between two snapshots."""
    before = before or {}
    after = after or {}
    changes: dict[str, dict[str, Any]] = {}
    for key in before.keys() | after.keys():
        old = before.get(key)
        new = after.get(key)
        if old != new:
            changes[key] = {"from": old, "to": new}
    return changes