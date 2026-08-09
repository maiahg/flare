from __future__ import annotations

import re

_MUTATING = re.compile(
    r"\b(roll ?back|rolled ?back|revert|redeploy|deploy|restart|reboot|"
    r"scale|resize|disable|enable|toggle|flip|kill|terminate|drain|failover|"
    r"fail over|flush|purge|truncate|delete|drop|throttle|rate[- ]limit|"
    r"page|notify|publish|announce|apply|patch|hotfix|rotate|reset)\b",
    re.IGNORECASE,
)

_OBSERVATIONAL = re.compile(
    r"\b(monitor|monitoring|observe|watch|keep an eye|wait|gather|collect|"
    r"investigate|inspect|review|measure|confirm|verify)\b",
    re.IGNORECASE,
)


def is_mutating(text: str) -> bool:
    """True if the option describes changing something."""
    return bool(_MUTATING.search(text or ""))


def requires_approval(text: str) -> bool:
    """Whether this mitigation option must be human-approved"""
    if is_mutating(text):
        return True
    return not _OBSERVATIONAL.search(text or "")