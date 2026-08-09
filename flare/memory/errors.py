from __future__ import annotations


class MemoryStoreError(Exception):
    """Base class for every memory-store violation."""


class ProvenanceError(MemoryStoreError):
    """A claim was created without a complete provenance envelope."""


class ImmutableFieldError(MemoryStoreError):
    """An update tried to change a field that is immutable."""


class UnknownFieldError(MemoryStoreError):
    """An update named a field that is not a column on the target model."""


class InvalidStatusError(MemoryStoreError):
    """A status value is not in the allowed set for that claim type."""


class EntityNotFoundError(MemoryStoreError):
    """No row exists for the requested model + id."""

class HumanAuthorityError(MemoryStoreError):
    """An agent tried to overwrite a field a human already decided."""

class UnmanagedWriteError(MemoryStoreError):
    """A memory table was written outside the repository."""