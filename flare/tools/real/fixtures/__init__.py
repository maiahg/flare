from __future__ import annotations

import json
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

_DIR = Path(__file__).parent


@lru_cache(maxsize=32)
def load(name: str) -> dict[str, Any]:
    """Load a recorded response body."""
    data: dict[str, Any] = json.loads((_DIR / f"{name}.json").read_text("utf-8"))
    return data


Router = Callable[[httpx.Request], httpx.Response]


def fixture_transport(routes: dict[str, str]) -> httpx.MockTransport:
    """Serve recorded bodies for path prefixes, 404 for anything else."""

    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, fixture in routes.items():
            if request.url.path.startswith(prefix):
                return httpx.Response(200, json=load(fixture))
        return httpx.Response(404, json={"message": f"no fixture for {request.url.path}"})

    return httpx.MockTransport(handler)


def dead_transport(*, timeout: bool = False) -> httpx.MockTransport:
    """A backend that is down — refused connections, or hangs until timeout."""

    def handler(request: httpx.Request) -> httpx.Response:
        if timeout:
            raise httpx.ReadTimeout("timed out", request=request)
        raise httpx.ConnectError("connection refused", request=request)

    return httpx.MockTransport(handler)


def malformed_transport() -> httpx.MockTransport:
    """A backend that is up but useless: 500s, then truncated JSON."""
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] % 2:
            return httpx.Response(500, text="internal server error")
        return httpx.Response(200, content=b'{"status": "suc')

    return httpx.MockTransport(handler)