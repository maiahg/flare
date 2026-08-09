from __future__ import annotations


class SteeringError(Exception):
    """Base class for a rejected steering request."""


class NotFoundError(SteeringError):
    """The entity does not exist, or belongs to another incident."""


class ValidationError(SteeringError):
    """The request is malformed: unknown enum value, or nothing to change."""


class ConflictError(SteeringError):
    """The request contradicts current state (e.g. deciding a settled approval)."""