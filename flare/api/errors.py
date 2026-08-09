from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from flare.memory.errors import (
    EntityNotFoundError,
    HumanAuthorityError,
    ImmutableFieldError,
    InvalidStatusError,
    MemoryStoreError,
    ProvenanceError,
    UnknownFieldError,
)
from flare.steering.errors import (
    ConflictError,
    NotFoundError,
    SteeringError,
    ValidationError,
)

#: Exception type -> status code.
_STATUS_BY_TYPE: dict[type[Exception], int] = {
    # steering (bad request)
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ValidationError: status.HTTP_400_BAD_REQUEST,
    ConflictError: status.HTTP_409_CONFLICT,
    SteeringError: status.HTTP_400_BAD_REQUEST,
    # memory store (violated invariant)
    EntityNotFoundError: status.HTTP_404_NOT_FOUND,
    HumanAuthorityError: status.HTTP_409_CONFLICT,
    ImmutableFieldError: status.HTTP_409_CONFLICT,
    InvalidStatusError: status.HTTP_400_BAD_REQUEST,
    ProvenanceError: status.HTTP_400_BAD_REQUEST,
    UnknownFieldError: status.HTTP_400_BAD_REQUEST,
    MemoryStoreError: status.HTTP_400_BAD_REQUEST,
}


def status_for(exc: Exception) -> int:
    for klass in type(exc).__mro__:
        code = _STATUS_BY_TYPE.get(klass)
        if code is not None:
            return code
    return status.HTTP_400_BAD_REQUEST


async def _handle(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status_for(exc),
        content={"detail": str(exc), "error": type(exc).__name__},
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers for the steering + memory error families."""
    app.add_exception_handler(SteeringError, _handle)
    app.add_exception_handler(MemoryStoreError, _handle)