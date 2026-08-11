from __future__ import annotations

import json

_REASONING_BLOCKS: tuple[tuple[str, str], ...] = (
    ("<think>", "</think>"),
    ("<thinking>", "</thinking>"),
    ("<reasoning>", "</reasoning>"),
    ("<|thinking|>", "<|/thinking|>"),
    ("◁think▷", "◁/think▷"),
)

_OPENERS = {"{": "}", "[": "]"}


def strip_reasoning(text: str) -> str:
    out = text
    for opener, closer in _REASONING_BLOCKS:
        while True:
            start = out.find(opener)
            if start == -1:
                break
            end = out.find(closer, start + len(opener))
            if end == -1:
                out = out[:start] + out[start + len(opener) :]
                break
            out = out[:start] + out[end + len(closer) :]
    return out


def _fenced_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    rest = text
    while True:
        start = rest.find("```")
        if start == -1:
            break
        after = rest[start + 3 :]
        newline = after.find("\n")
        if newline != -1 and after[:newline].strip().isalpha():
            after = after[newline + 1 :]
        end = after.find("```")
        if end == -1:
            blocks.append(after)
            break
        blocks.append(after[:end])
        rest = after[end + 3 :]
    return blocks


def _balanced(text: str) -> str | None:
    start = -1
    closer = ""
    for index, char in enumerate(text):
        if char in _OPENERS:
            start = index
            closer = _OPENERS[char]
            break
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in _OPENERS:
            depth += 1
        elif char in ("}", "]"):
            depth -= 1
            if depth == 0:
                return text[start : index + 1] if char == closer else None
    return None


def _parses(candidate: str) -> bool:
    try:
        json.loads(candidate)
    except (ValueError, TypeError):
        return False
    return True


def extract_json(content: str) -> str:
    if not content:
        return content
    stripped = strip_reasoning(content).strip()

    candidates: list[str] = [stripped]
    candidates.extend(block.strip() for block in _fenced_blocks(stripped))
    candidates.extend(
        found
        for found in (_balanced(candidate) for candidate in list(candidates))
        if found
    )

    for candidate in candidates:
        if candidate and _parses(candidate):
            return candidate
    for candidate in candidates:
        if candidate:
            return candidate
    return content


__all__ = ["extract_json", "strip_reasoning"]
