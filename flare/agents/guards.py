from __future__ import annotations

import re

from flare.agents.schemas import ExtractedSignal

_PR_LINK = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/(\d+)")
_DEPLOY = re.compile(r"\bdeploy[- #]?(\d+)\b", re.IGNORECASE)
_FLAG = re.compile(r"\b(?:flag|feature)[:= ]+([a-z0-9_.-]+)\b", re.IGNORECASE)
_ERROR = re.compile(r"\b([A-Z][A-Za-z0-9]*Error|[45]\d{2})s?\b")
_TIME_WINDOW = re.compile(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b")

#: `abc1234` … `abc1234def` — a git short sha. Bounded to avoid matching words.
_COMMIT = re.compile(r"\b(?:commit|sha)[: ]+([0-9a-f]{7,40})\b", re.IGNORECASE)
#: Service names as they appear in this stack
_SERVICE = re.compile(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+)*-(?:api|svc|service|worker))\b")
#: Latency/percentile/rate metrics.
_METRIC = re.compile(
    r"\b(p\d{2,3}|error[- ]rate|latency|throughput|saturation|cpu|memory|qps)\b",
    re.IGNORECASE,
)
#: Config/infra knobs people call out in channel.
_CONFIG = re.compile(
    r"\b(pool[- ]size|timeout|max[- ]conn\w*|replica\w*|autoscal\w*|quota|limit)\b",
    re.IGNORECASE,
)
#: A mitigation was applied — high-value: it changes the incident's state.
_MITIGATION = re.compile(
    r"\b(rolled? back|rollback|reverted?|scaled? (?:up|down)|restarted?|"
    r"failed over|failover|disabled the flag|drained|hotfix(?:ed)?)\b",
    re.IGNORECASE,
)
#: A human correcting the record — always worth a run.
_CORRECTION = re.compile(
    r"\b(correction|actually,|scratch that|i was wrong|to correct|ignore what i said)",
    re.IGNORECASE,
)
#: A human contradicting memory — negation aimed at a prior claim.
_CONTRADICTION = re.compile(
    r"\b(that'?s not|isn'?t|wasn'?t|didn'?t|no longer|ruled out|not the cause|"
    r"unrelated to)\b",
    re.IGNORECASE,
)
#: Explicit asks. `/flare investigate|validate` must always trigger.
_COMMAND = re.compile(r"/flare\s+(investigate|validate)\b", re.IGNORECASE)
#: Bare symptom language. Weak on its own (it rarely names an artifact you can
#: query) but it is what a first "something is broken" message looks like.
_SYMPTOM = re.compile(
    r"\b(throwing|failing|erroring|timing out|timeouts?|degraded|degradation|"
    r"spik\w+|elevated|outage|stuck|unavailable|5xx|4xx)\b",
    re.IGNORECASE,
)
#: Affected population.
_SEGMENT = re.compile(
    r"\b(\d{1,3}(?:\.\d+)?%\s+of\s+\w+|all (?:merchants|customers|users)|"
    r"(?:plus|shopify plus|enterprise|trial) (?:merchants|shops))\b",
    re.IGNORECASE,
)

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
    for m in _COMMIT.finditer(text):
        add("commit", m.group(1))
    for m in _SERVICE.finditer(text):
        add("service", m.group(1))
    for m in _METRIC.finditer(text):
        add("metric", m.group(1).lower())
    for m in _CONFIG.finditer(text):
        add("config", m.group(1).lower())
    for m in _MITIGATION.finditer(text):
        add("mitigation", m.group(0))
    for m in _SYMPTOM.finditer(text):
        add("symptom", m.group(1).lower())
    for m in _SEGMENT.finditer(text):
        add("segment", m.group(0))
    for m in _CORRECTION.finditer(text):
        add("correction", m.group(0))
    for m in _CONTRADICTION.finditer(text):
        add("contradiction", m.group(0))
    for m in _COMMAND.finditer(text):
        add("command", m.group(0))
    return out