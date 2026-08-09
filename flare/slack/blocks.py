from __future__ import annotations

import uuid
from typing import Any

# ---- action ids ------------------------------------------------------------
ACTION_HYPOTHESIS_CONFIRM = "hypothesis:confirm"
ACTION_HYPOTHESIS_REJECT = "hypothesis:reject"
ACTION_HYPOTHESIS_INVESTIGATE = "hypothesis:investigate"
ACTION_HYPOTHESIS_EVIDENCE = "hypothesis:evidence"
ACTION_QUESTION_ASSIGN = "question:assign"
ACTION_QUESTION_ANSWERED = "question:answered"
ACTION_APPROVAL_APPROVE = "approval:approve"
ACTION_APPROVAL_REJECT = "approval:reject"

INTERACTIVE_ACTIONS = frozenset(
    {
        ACTION_HYPOTHESIS_CONFIRM,
        ACTION_HYPOTHESIS_REJECT,
        ACTION_HYPOTHESIS_INVESTIGATE,
        ACTION_HYPOTHESIS_EVIDENCE,
        ACTION_QUESTION_ASSIGN,
        ACTION_QUESTION_ANSWERED,
        ACTION_APPROVAL_APPROVE,
        ACTION_APPROVAL_REJECT,
    }
)


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _button(
    text: str, action_id: str, value: str, *, style: str | None = None
) -> dict[str, Any]:
    button: dict[str, Any] = {
        "type": "button",
        "text": {"type": "plain_text", "text": text},
        "action_id": action_id,
        "value": value,
    }
    if style:
        button["style"] = style
    return button


def _link(url: str, label: str) -> str:
    return f"<{url}|{label}>"


def hypothesis_card(
    *,
    hypothesis_id: uuid.UUID,
    statement: str,
    likelihood: float | None,
    status: str,
    supporting: int,
    contradicting: int,
    dashboard_url: str,
) -> list[dict[str, Any]]:
    """Confirm · Reject · Investigate · View evidence."""
    odds = f"{float(likelihood):.0%}" if likelihood is not None else "—"
    header = (
        f"*Hypothesis* ({status}, likelihood {odds})\n{statement}\n"
        f"_{supporting} supporting · {contradicting} contradicting_"
    )
    value = str(hypothesis_id)
    return [
        _section(header),
        {
            "type": "actions",
            "block_id": f"hypothesis:{value}",
            "elements": [
                _button("Confirm", ACTION_HYPOTHESIS_CONFIRM, value, style="primary"),
                _button("Reject", ACTION_HYPOTHESIS_REJECT, value, style="danger"),
                _button("Investigate", ACTION_HYPOTHESIS_INVESTIGATE, value),
                _button("View evidence", ACTION_HYPOTHESIS_EVIDENCE, value),
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": _link(dashboard_url, "Open in dashboard →")}
            ],
        },
    ]


def question_card(
    *,
    question_id: uuid.UUID,
    question: str,
    owner: str | None,
    status: str,
    dashboard_url: str,
) -> list[dict[str, Any]]:
    """Assign to @user · Mark answered."""
    value = str(question_id)
    owner_text = f" · owner {owner}" if owner else " · unassigned"
    return [
        _section(f"*Open question* ({status}{owner_text})\n{question}"),
        {
            "type": "actions",
            "block_id": f"question:{value}",
            "elements": [
                {
                    "type": "users_select",
                    "action_id": ACTION_QUESTION_ASSIGN,
                    "placeholder": {"type": "plain_text", "text": "Assign to…"},
                },
                _button("Mark answered", ACTION_QUESTION_ANSWERED, value),
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": _link(dashboard_url, "Open in dashboard →")}
            ],
        },
    ]


def mitigation_card(
    *,
    approval_id: uuid.UUID,
    title: str,
    description: str,
    risk: str,
    reversibility: str,
    expected_benefit: str,
    dashboard_url: str,
    status: str = "proposed",
    decided: str = "pending",
) -> list[dict[str, Any]]:
    """Approve · Reject for a proposed mitigation"""
    value = str(approval_id)
    blocks: list[dict[str, Any]] = [
        _section(
            f":shield: *Mitigation proposal*\n*{title}*\n{description}"
        ),
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Risk:* {risk}"},
                {"type": "mrkdwn", "text": f"*Reversibility:* {reversibility}"},
                {"type": "mrkdwn", "text": f"*Expected benefit:* {expected_benefit}"},
                {"type": "mrkdwn", "text": f"*Status:* {status}"},
            ],
        },
    ]
    if decided == "not required":
        blocks.append(_section("_No approval required — this option changes nothing._"))
    elif decided == "pending":
        blocks.append(
            {
                "type": "actions",
                "block_id": f"approval:{value}",
                "elements": [
                    _button("Approve", ACTION_APPROVAL_APPROVE, value, style="primary"),
                    _button("Reject", ACTION_APPROVAL_REJECT, value, style="danger"),
                ],
            }
        )
    else:
        blocks.append(_section(f"_Already {decided}._"))
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Approval records the decision — Flare never applies a "
                    f"mitigation. {_link(dashboard_url, 'Details →')}",
                }
            ],
        }
    )
    return blocks


def ephemeral(text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """An ephemeral slash-command response (``text`` is the a11y fallback)."""
    payload: dict[str, Any] = {"response_type": "ephemeral", "text": text}
    if blocks:
        payload["blocks"] = blocks
    return payload


def in_channel(text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A visible-to-channel response — only for things that need witnesses."""
    payload: dict[str, Any] = {"response_type": "in_channel", "text": text}
    if blocks:
        payload["blocks"] = blocks
    return payload