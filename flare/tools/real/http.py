from __future__ import annotations

import json
from typing import Any

import httpx

from flare.tools.interface import BackendUnavailable


class ReadOnlyHttpBackend:
    """Issues GETs against one base URL. Never anything else."""

    def __init__(
        self,
        base_url: str,
        *,
        label: str,
        headers: dict[str, str] | None = None,
        timeout_s: float = 5.0,
        max_bytes: int = 2_000_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._label = label
        self._headers = headers or {}
        self._timeout_s = timeout_s
        self._max_bytes = max_bytes
        self._transport = transport

    @property
    def label(self) -> str:
        return self._label

    async def get_json(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        """GET ``path`` and parse JSON, or raise :class:`BackendUnavailable`."""
        url = f"{self._base_url}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_s,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.get(url, params=params, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise BackendUnavailable(
                f"{self._label} timed out after {self._timeout_s}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise BackendUnavailable(f"{self._label} unreachable: {exc}") from exc

        if response.status_code == 401 or response.status_code == 403:
            raise BackendUnavailable(
                f"{self._label} rejected our credentials (HTTP "
                f"{response.status_code}) — check the read-only token"
            )
        if response.status_code >= 400:
            raise BackendUnavailable(
                f"{self._label} returned HTTP {response.status_code}"
            )

        body = response.content
        if len(body) > self._max_bytes:
            raise BackendUnavailable(
                f"{self._label} returned {len(body)} bytes, over the "
                f"{self._max_bytes} limit — narrow the query"
            )
        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BackendUnavailable(
                f"{self._label} returned a non-JSON response"
            ) from exc