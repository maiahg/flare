from __future__ import annotations

import re
from typing import Any

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_SLACK_TOKEN = re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]+)\b")
_BEARER = re.compile(r"\b(sk-[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]+)\b")
_CARD = re.compile(r"\b(?:\d[ -]*?){13,16}\b")

_AWS_KEY = re.compile(r"\b((?:AKIA|ASIA|AGPA|AIDA)[0-9A-Z]{12,20})\b")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")

_ASSIGNED_SECRET = re.compile(
    r"(?i)\b([a-z0-9_.-]*(?:password|passwd|secret|api[_-]?key|access[_-]?key|"
    r"token|credential)[a-z0-9_.-]*)\s*[:=]\s*[\"']?([^\s\"',;}]{4,})[\"']?"
)

_DSN_CREDENTIALS = re.compile(r"\b([a-z][a-z0-9+.-]*://)([^\s:/@]+):([^\s@]+)@")

_REPLACEMENTS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("private_key", _PRIVATE_KEY, "[private-key]"),
    ("jwt", _JWT, "[jwt]"),
    ("aws_key", _AWS_KEY, "[aws-key]"),
    ("slack_token", _SLACK_TOKEN, "[token]"),
    ("bearer", _BEARER, "[secret]"),
    ("dsn", _DSN_CREDENTIALS, r"\1\2:[secret]@"),
    ("assigned_secret", _ASSIGNED_SECRET, r"\1=[secret]"),
    ("email", _EMAIL, "[email]"),
    ("card", _CARD, "[card]"),
)


def redact(text: str) -> str:
    """Strip PII/secrets from a string before it is sent out or stored."""
    scrubbed, _ = redact_report(text)
    return scrubbed


def redact_report(text: str) -> tuple[str, dict[str, int]]:
    """Redact, and report how many matches each pattern replaced."""
    hits: dict[str, int] = {}
    for label, pattern, replacement in _REPLACEMENTS:
        text, count = pattern.subn(replacement, text)
        if count:
            hits[label] = hits.get(label, 0) + count
    return text, hits


def redact_value(value: Any) -> tuple[Any, dict[str, int]]:
    """Recursively redact strings inside dicts / lists / scalars."""
    hits: dict[str, int] = {}

    def _merge(counts: dict[str, int]) -> None:
        for key, count in counts.items():
            hits[key] = hits.get(key, 0) + count

    def _walk(node: Any) -> Any:
        if isinstance(node, str):
            scrubbed, counts = redact_report(node)
            _merge(counts)
            return scrubbed
        if isinstance(node, dict):
            out = {}
            for key, item in node.items():
                new_key = key
                if isinstance(key, str):
                    new_key, counts = redact_report(key)
                    _merge(counts)
                out[new_key] = _walk(item)
            return out
        if isinstance(node, list):
            return [_walk(item) for item in node]
        if isinstance(node, tuple):
            return tuple(_walk(item) for item in node)
        return node

    return _walk(value), hits