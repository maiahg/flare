from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flare.agents.schemas import ExtractedSignal
from flare.models.claims import (
    Decision,
    Evidence,
    Fact,
    Hypothesis,
    OpenQuestion,
    Summary,
    TimelineEntry,
)
from flare.models.ingestion import Signal

#: Signal types that are always novel — an explicit human ask or retraction.
_ALWAYS_NOVEL = frozenset({"command", "correction"})

#: Signal types whose *presence* is what matters, mapped to a scoring category.
CATEGORIES: dict[str, str] = {
    "service": "novel_service",
    "symptom": "symptom",
    "time_window": "new_time_window",
    "metric": "new_observation",
    "log": "new_observation",
    "stacktrace": "new_error",
    "error": "new_error",
    "deploy": "change_event",
    "pr": "change_event",
    "commit": "change_event",
    "config": "change_event",
    "flag": "change_event",
    "mitigation": "mitigation",
    "segment": "new_segment",
    "region": "new_segment",
    "plan": "new_segment",
    "endpoint": "new_segment",
    "open_question": "question",
    "contradiction": "contradiction",
    "correction": "correction",
    "command": "command",
}

_WORD = re.compile(r"[a-z0-9]+")
_NEGATION = re.compile(
    r"\b(not|isn'?t|wasn'?t|aren'?t|didn'?t|doesn'?t|never|no longer|ruled out|"
    r"unrelated)\b",
    re.IGNORECASE,
)
#: Words too common to prove a message is talking about a remembered claim.
_STOPWORDS = frozenset(
    """a an and are as at be but by for from has have in is it its of on or that
    the this to was were will with we you i not no do does did been being they
    them our your there here what when which who why how""".split()
)


def _normalize(value: object) -> str:
    """Lowercased, punctuation-stripped text for comparison."""
    text = value if isinstance(value, str) else str(value)
    return " ".join(_WORD.findall(text.lower()))


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS and len(w) > 2}


def signal_text(signal: ExtractedSignal) -> str:
    """The comparable text of a signal, whatever shape its ``value`` took."""
    value = signal.value or {}
    if "text" in value:
        return str(value["text"])
    return " ".join(str(v) for v in value.values())


@dataclass
class MemoryView:
    """What the incident already knows, in comparison-ready form."""

    #: ``signal_type -> {normalized value}`` from previously extracted signals.
    known_signals: dict[str, set[str]] = field(default_factory=dict)
    #: Normalized text of every active claim + the latest summary.
    corpus: str = ""
    #: Content words of the corpus, for contradiction overlap checks.
    corpus_words: set[str] = field(default_factory=set)

    def has_signal(self, signal_type: str, normalized: str) -> bool:
        return normalized in self.known_signals.get(signal_type, set())

    def mentions(self, normalized: str) -> bool:
        """True if the corpus already contains this exact phrase."""
        return bool(normalized) and normalized in self.corpus


async def load_memory_view(
    session: AsyncSession,
    incident_id: uuid.UUID,
    *,
    exclude_message_id: uuid.UUID | None = None,
) -> MemoryView:
    """Snapshot the incident's current knowledge for the novelty diff.

    ``exclude_message_id`` drops the signals extracted from the message being
    judged — Scribe persists them before triage runs, so without this every
    message would look like a restatement of itself.
    """
    view = MemoryView()

    stmt = select(Signal.signal_type, Signal.value).where(Signal.incident_id == incident_id)
    if exclude_message_id is not None:
        stmt = stmt.where(Signal.message_id != exclude_message_id)
    for signal_type, value in (await session.execute(stmt)).all():
        if not signal_type:
            continue
        text = (value or {}).get("text") if isinstance(value, dict) else None
        normalized = _normalize(text if text is not None else value)
        view.known_signals.setdefault(signal_type, set()).add(normalized)

    texts: list[str] = []
    for model, column in (
        (TimelineEntry, TimelineEntry.description),
        (Fact, Fact.statement),
        (Hypothesis, Hypothesis.statement),
        (OpenQuestion, OpenQuestion.question),
        (Decision, Decision.statement),
        (Evidence, Evidence.title),
        (Evidence, Evidence.body),
    ):
        rows = await session.scalars(
            select(column).where(
                model.incident_id == incident_id,
                model.status.notin_(("rejected", "superseded")),
            )
        )
        texts.extend(str(r) for r in rows if r)

    summaries = await session.scalars(
        select(Summary.body)
        .where(Summary.incident_id == incident_id, Summary.scope == "current")
        .order_by(Summary.created_at.desc())
        .limit(1)
    )
    texts.extend(str(s) for s in summaries if s)

    view.corpus = _normalize(" | ".join(texts))
    view.corpus_words = _content_words(view.corpus)
    return view


@dataclass(frozen=True)
class NoveltyVerdict:
    """Per-signal novelty decision, carried into scoring and persisted."""

    signal: ExtractedSignal
    novel: bool
    category: str
    reason: str

    @property
    def signal_type(self) -> str:
        return self.signal.signal_type


def _is_contradiction(text: str, view: MemoryView) -> bool:
    """A negation that is about something memory already holds. """
    if not _NEGATION.search(text):
        return False
    overlap = _content_words(text) & view.corpus_words
    return len(overlap) >= 2


def evaluate_novelty(
    signals: list[ExtractedSignal], view: MemoryView, *, text: str = ""
) -> list[NoveltyVerdict]:
    """Diff freshly extracted signals against memory"""
    contradicts_memory = _is_contradiction(text, view) if text else False
    verdicts: list[NoveltyVerdict] = []

    for signal in signals:
        stype = signal.signal_type
        value = _normalize(signal_text(signal))
        category = CATEGORIES.get(stype, "other")

        if stype in _ALWAYS_NOVEL:
            verdicts.append(
                NoveltyVerdict(signal, True, category, f"explicit {stype} from a human")
            )
            continue

        if stype == "contradiction":
            if contradicts_memory:
                verdicts.append(
                    NoveltyVerdict(
                        signal, True, "contradiction", "contradicts existing memory"
                    )
                )
            else:
                verdicts.append(
                    NoveltyVerdict(
                        signal, False, "contradiction", "negation not aimed at memory"
                    )
                )
            continue

        if view.has_signal(stype, value):
            verdicts.append(
                NoveltyVerdict(signal, False, category, f"{stype} already seen: {value}")
            )
            continue

        if view.mentions(value):
            verdicts.append(
                NoveltyVerdict(signal, False, category, f"already in memory: {value}")
            )
            continue

        verdicts.append(
            NoveltyVerdict(signal, True, category, f"new {stype}: {value}")
        )

    # A contradiction detected in the sentence but not extracted as a signal
    # still deserves a run — surface it as its own verdict.
    if contradicts_memory and not any(
        v.category == "contradiction" and v.novel for v in verdicts
    ):
        verdicts.append(
            NoveltyVerdict(
                ExtractedSignal(
                    signal_type="contradiction",
                    value={"text": text[:200]},
                    confidence=0.9,
                ),
                True,
                "contradiction",
                "message negates something already in memory",
            )
        )

    return verdicts