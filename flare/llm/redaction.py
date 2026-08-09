from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_TOKEN = re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]+)\b")          # Slack tokens
_BEARER = re.compile(r"\b(sk-[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]+)\b")
_CARD = re.compile(r"\b(?:\d[ -]*?){13,16}\b")

_REPLACEMENTS = (
    (_EMAIL, "[email]"),
    (_TOKEN, "[token]"),
    (_BEARER, "[secret]"),
    (_CARD, "[card]"),
)


def redact(text: str) -> str:
    """Strip PII/secrets from a string before it is sent out or stored."""
    for pattern, repl in _REPLACEMENTS:
        text = pattern.sub(repl, text)
    return text