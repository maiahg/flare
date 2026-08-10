from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from flare.models.claims import COMMS_AUDIENCES
from flare.secrets import slack_bot_token

_logger = logging.getLogger("flare.slack.modals")

_SLACK_API = "https://slack.com/api"

VIEW_METHODS = frozenset({"views.open", "views.update"})

#: Modal identity. The submit handler dispatches on the callback id.
CALLBACK_COMMS_DRAFT = "flare:comms_draft"
BLOCK_COMMS_BODY = "comms:body"
ACTION_COMMS_BODY = "comms:body_input"
ACTION_COMMS_AUDIENCE = "comms:audience"


class SlackModals:
    """``views.open`` / ``views.update``. No message-posting method exists."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token if token is not None else slack_bot_token()

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if method not in VIEW_METHODS:
            raise ValueError(
                f"{method} is not a view method; this client cannot post messages"
            )
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{_SLACK_API}/{method}",
                headers={"Authorization": f"Bearer {self._token}"},
                json=payload,
            )
        data: dict[str, Any] = resp.json()
        if not data.get("ok"):
            _logger.warning("%s failed: %s", method, data.get("error"))
        return data

    async def open(self, *, trigger_id: str, view: dict[str, Any]) -> str | None:
        """Open a modal; returns the view id (needed to update it later)."""
        data = await self._call("views.open", {"trigger_id": trigger_id, "view": view})
        return str((data.get("view") or {}).get("id") or "") or None

    async def update(self, *, view_id: str, view: dict[str, Any]) -> dict[str, Any]:
        return await self._call("views.update", {"view_id": view_id, "view": view})


# ---- view payloads ---------------------------------------------------------


def _metadata(**fields: Any) -> str:
    return json.dumps({k: str(v) for k, v in fields.items() if v is not None})


def parse_metadata(raw: str | None) -> dict[str, str]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _audience_select(audience: str) -> dict[str, Any]:
    def option(name: str) -> dict[str, Any]:
        return {"text": {"type": "plain_text", "text": name}, "value": name}

    return {
        "type": "section",
        "block_id": "comms:audience_block",
        "text": {"type": "mrkdwn", "text": "*Audience*"},
        "accessory": {
            "type": "static_select",
            "action_id": ACTION_COMMS_AUDIENCE,
            "options": [option(a) for a in COMMS_AUDIENCES],
            "initial_option": option(audience),
        },
    }


def loading_view(*, incident_id: uuid.UUID, audience: str) -> dict[str, Any]:
    """What goes up inside Slack's 3s budget while the draft is written."""
    return {
        "type": "modal",
        "callback_id": CALLBACK_COMMS_DRAFT,
        "private_metadata": _metadata(incident_id=incident_id, audience=audience),
        "title": {"type": "plain_text", "text": "Comms draft"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _audience_select(audience),
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":writing_hand: Drafting the *{audience}* update…",
                },
            },
        ],
    }


def draft_view(
    *,
    incident_id: uuid.UUID,
    draft_id: uuid.UUID,
    audience: str,
    body: str,
    version: int,
    status: str,
    dashboard_url: str,
    degraded: bool = False,
) -> dict[str, Any]:
    """The editable draft: audience selector, body, `Approve draft`."""
    blocks: list[dict[str, Any]] = [
        _audience_select(audience),
        {
            "type": "input",
            "block_id": BLOCK_COMMS_BODY,
            "label": {"type": "plain_text", "text": f"Draft v{version} ({status})"},
            "element": {
                "type": "plain_text_input",
                "action_id": ACTION_COMMS_BODY,
                "multiline": True,
                "initial_value": body,
            },
            "hint": {
                "type": "plain_text",
                "text": "Editing saves a new version before approving.",
            },
        },
    ]
    if degraded:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": ":warning: Written without the model — this is a "
                        "restatement of memory, not a drafted update.",
                    }
                ],
            }
        )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Approving marks this draft ready. *Flare never sends "
                    f"external comms* — copy the text and send it. "
                    f"<{dashboard_url}|Incident →>",
                }
            ],
        }
    )
    return {
        "type": "modal",
        "callback_id": CALLBACK_COMMS_DRAFT,
        "private_metadata": _metadata(
            incident_id=incident_id, audience=audience, draft_id=draft_id
        ),
        "title": {"type": "plain_text", "text": "Comms draft"},
        "submit": {"type": "plain_text", "text": "Approve draft"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def submitted_body(view: dict[str, Any]) -> str:
    """Pull the edited body out of a ``view_submission`` payload."""
    values = (view.get("state") or {}).get("values") or {}
    block = values.get(BLOCK_COMMS_BODY) or {}
    element = block.get(ACTION_COMMS_BODY) or {}
    return str(element.get("value") or "")


__all__ = [
    "ACTION_COMMS_AUDIENCE",
    "ACTION_COMMS_BODY",
    "BLOCK_COMMS_BODY",
    "CALLBACK_COMMS_DRAFT",
    "VIEW_METHODS",
    "SlackModals",
    "draft_view",
    "loading_view",
    "parse_metadata",
    "submitted_body",
]