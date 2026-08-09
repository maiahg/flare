from __future__ import annotations


class ToolError(Exception):
    """Base class for Tool Broker errors."""


class NotAllowlistedError(ToolError):
    """Raised when an agent asks for a tool that is not registered."""


class RateLimitedToolError(ToolError):
    """Raised when the per-(incident, tool) rate limit is exceeded."""


class ToolTimeoutError(ToolError):
    """Raised internally when an adapter exceeds the call timeout."""


class ToolArgsError(ToolError):
    """Raised when a tool is called with arguments its spec rejects."""


class MutatingToolError(ToolError):
    """Raised when something tries to mount an adapter that can change the world.