from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from flare.events.bus import EVENT_SLACK_POSTED, Event, publish
from flare.secrets import slack_bot_token

_PROACTIVE_MODES = frozenset({"assist", "active"})
_SLACK_POST_URL = "https://slack.com/api/chat.postMessage"

_logger = logging.getLogger("flare.slack.posting")


def can_post_proactively(mode: str) -> bool:
    """True only in modes where the bot may post without being asked."""
    return mode in _PROACTIVE_MODES


class SlackPoster:
    """Minimal `chat.postMessage` client using the bot token."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token if token is not None else slack_bot_token()

    async def post_message(
        self,
        channel: str,
        text: str,
        *,
        thread_ts: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"channel": channel, "text": text}
        if thread_ts is not None:
            payload["thread_ts"] = thread_ts
        if blocks:
            payload["blocks"] = blocks
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _SLACK_POST_URL,
                headers={"Authorization": f"Bearer {self._token}"},
                json=payload,
            )
        data: dict[str, Any] = resp.json()
        if not data.get("ok"):
            _logger.warning("slack post failed: %s", data.get("error"))
        return data


async def post_incident_card(
    poster: SlackPoster,
    *,
    channel: str,
    title: str,
    severity: str,
    dashboard_url: str | None = None,
) -> str | None:
    """Post the pinned incident card + 'investigating…'. Returns its ts."""
    text = f":rotating_light: *{title}* ({severity})\nFlare is investigating…"
    if dashboard_url:
        text += f"\n<{dashboard_url}|Open dashboard →>"
    result = await poster.post_message(channel, text)
    return result.get("ts")


class InvestigationSlackPoster:
    """Adapts `SlackPoster` to the graph's `InvestigationPoster` protocol."""

    def __init__(
        self,
        poster: SlackPoster,
        *,
        channel: str,
        incident_id: uuid.UUID,
        mode: str,
        thread_ts: str | None = None,
        force: bool = False,
    ) -> None:
        self._poster = poster
        self._channel = channel
        self._incident_id = incident_id
        self._mode = mode
        self._thread_ts = thread_ts
        self._force = force

    def _may_post(self) -> bool:
        return self._force or can_post_proactively(self._mode)

    async def post_intent(self, checking: list[str]) -> None:
        if not self._may_post():
            return
        text = f":mag: Checking {', '.join(checking)}…"
        await self._poster.post_message(
            self._channel, text, thread_ts=self._thread_ts
        )
        await self._announce("intent")

    async def post_findings(
        self, *, summary: str | None, top_hypothesis: str | None, dashboard_url: str
    ) -> None:
        if not self._may_post():
            return
        lines = [":clipboard: *Findings*"]
        if summary:
            lines.append(summary)
        if top_hypothesis:
            lines.append(f"*Leading hypothesis:* {top_hypothesis}")
        lines.append(f"<{dashboard_url}|Full investigation →>")
        await self._poster.post_message(
            self._channel, "\n".join(lines), thread_ts=self._thread_ts
        )
        await self._announce("findings")

    async def post_verdict(
        self, *, claim: str, verdict: str, rationale: str, dashboard_url: str
    ) -> None:
        """Post a claim-verification verdict."""
        if not self._may_post():
            return
        icon = {
            "supported": ":white_check_mark: *Verified*",
            "contradicted": ":x: *Contradicted*",
            "inconclusive": ":grey_question: *Inconclusive*",
        }.get(verdict, f"*{verdict}*")
        lines = [f"{icon}: {claim}"]
        if rationale:
            lines.append(rationale)
        lines.append(f"<{dashboard_url}|Full investigation →>")
        await self._poster.post_message(
            self._channel, "\n".join(lines), thread_ts=self._thread_ts
        )
        await self._announce("verdict")

    async def post_approval(
        self, *, blocks: list[dict[str, Any]], text: str
    ) -> None:
        """Post an approval card"""
        if not self._may_post():
            return
        await self._poster.post_message(self._channel, text, blocks=blocks)
        await self._announce("approval")

    async def post_raw(self, text: str) -> None:
        """Post an already-composed line"""
        if not self._may_post():
            return
        await self._poster.post_message(self._channel, text, thread_ts=self._thread_ts)
        await self._announce("nudge")

    async def _announce(self, kind: str) -> None:
        try:
            await publish(
                Event(
                    event=EVENT_SLACK_POSTED,
                    incident_id=self._incident_id,
                    data={"kind": kind},
                )
            )
        except Exception:
            _logger.debug("failed to publish slack.posted", exc_info=True)