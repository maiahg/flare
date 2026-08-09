from __future__ import annotations

import re

from flare.agents.schemas import ExtractedSignal

_PR_LINK = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/(\d+)")
_DEPLOY = re.compile(r"\bdeploy[- ]?(\d+)\b", re.IGNORECASE)
_FLAG = re.compile(r"\b(?:flag|feature)[:= ]+([a-z0-9_.-]+)\b", re.IGNORECASE)
_ERROR = re.compile(r"\b([A-Z][A-Za-z0-9]*Error|5\d{2}|4\d{2})\b")
_TIME_WINDOW = re.compile(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b")


def deterministic_signals(text: str) -> list[ExtractedSignal]:
    """Regex/entity guards — high-confidence structured signals."""
    out: list[ExtractedSignal] = []

    def add(signal_type: str, value: str) -> None:
        out.append(
            ExtractedSignal(signal_type=signal_type, value={"text": value}, confidence=0.99)
        )

    for m in _PR_LINK.finditer(text):
        add("pr", m.group(0))
    for m in _DEPLOY.finditer(text):
        add("deploy", m.group(0))
    for m in _FLAG.finditer(text):
        add("flag", m.group(1))
    for m in _ERROR.finditer(text):
        add("error", m.group(1))
    for m in _TIME_WINDOW.finditer(text):
        add("time_window", m.group(1))
    return out