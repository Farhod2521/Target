"""The questions the assistant could not answer, kept for the office.

Two things write a row. The assistant says so itself (``report_gap``): what
was asked, whether words or a look-up are missing, and what to add. Or it
searched the known fixes, found nothing every time and said no more - then
the search's own words are the title. The same question asked again is the
same row, counted, so the office writes first what is asked most.

The office then writes a ready answer - a help article, which
``help_search`` finds from that day on - or dismisses the row.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.exceptions import InputRefused, NotFound
from app.modules.accounts.models import User
from app.modules.assistant.constants import (
    GAP_COMPARE_ROWS,
    GAP_QUERIES,
    GAP_QUESTION_CHARS,
    GAP_SAME_SHARE,
    GAP_SAMPLES,
    GapStatus,
)
from app.modules.assistant.models import AssistantGap, HelpArticle
from core.assistant.tools import GAP_ANSWER

logger = logging.getLogger(__name__)

STEM: int = 5


class GapMissing(NotFound):
    def __init__(self) -> None:
        super().__init__("Savol topilmadi.")


def note_gap(
    db: Session,
    *,
    question: str,
    language: str,
    owner_id: str,
    message_id: str,
    report: dict[str, str] | None,
    searches: list[tuple[str, int]],
    now: datetime,
) -> AssistantGap | None:
    """Keep this turn's unanswered question, or nothing if it was answered.

    ``searches`` is each search of the known fixes with how many it found.
    Without the assistant's own report a row is written only when it
    searched and every search came back empty."""
    empty = [query for query, found in searches if not found and query.strip()]
    if report is None and (not searches or len(empty) != len(searches)):
        return None
    topic = _line(report["topic"] if report else empty[0])[:255]
    if not topic:
        return None
    kind = report["kind"] if report else GAP_ANSWER
    missing = _line(report["missing"]) if report else ""
    sample = {
        "question": question[:GAP_QUESTION_CHARS],
        "at": now.isoformat(),
        "owner_id": owner_id,
        "message_id": message_id,
    }
    row = _same(db, topic=topic, queries=empty)
    if row is None:
        row = AssistantGap(
            topic=topic,
            kind=kind,
            missing=missing,
            question=sample["question"],
            language=language,
            queries=empty[:GAP_QUERIES],
            samples=[sample],
            hits=1,
            last_asked_at=now,
            status=GapStatus.OPEN,
        )
        db.add(row)
        db.flush()
        return row
    row.hits += 1
    row.last_asked_at = now
    row.question = sample["question"]
    row.language = language
    row.samples = [sample, *(row.samples or [])][:GAP_SAMPLES]
    row.queries = list(dict.fromkeys([*(row.queries or []), *empty]))[:GAP_QUERIES]
    if missing and not row.missing:
        # The first asking was only an empty search; now the assistant said
        # what is missing.
        row.missing, row.kind = missing, kind
    if row.status == GapStatus.ANSWERED:
        # An answer was written and the assistant still did not find it.
        row.status, row.closed_at = GapStatus.OPEN, None
    db.flush()
    return row


def _line(words: str) -> str:
    return " ".join(str(words).split())


def _stems(words: str) -> frozenset[str]:
    from app.modules.assistant.selectors.help import _asked

    return frozenset(word[:STEM] for word in _asked(words))


def _same(db: Session, *, topic: str, queries: list[str]) -> AssistantGap | None:
    """The row this question already has: a search made in the same words,
    or a title sharing most of its words."""
    wanted = _stems(topic)
    asked = {_line(query).casefold() for query in queries}
    best: tuple[float, AssistantGap] | None = None
    rows = db.scalars(
        select(AssistantGap)
        .order_by(AssistantGap.last_asked_at.desc())
        .limit(GAP_COMPARE_ROWS)
        .with_for_update()
    )
    for row in rows:
        if asked & {_line(str(query)).casefold() for query in row.queries or ()}:
            return row
        theirs = _stems(row.topic)
        both = len(wanted | theirs)
        share = len(wanted & theirs) / both if both else 0.0
        if share >= GAP_SAME_SHARE and (best is None or share > best[0]):
            best = (share, row)
    return best[1] if best else None


# -- the office ---------------------------------------------------------------


def gap(db: Session, pk: uuid.UUID) -> AssistantGap:
    found = db.get(AssistantGap, pk)
    if found is None:
        raise GapMissing
    return found


def set_status(
    db: Session, *, row: AssistantGap, status: str, now: datetime
) -> AssistantGap:
    """Dismiss a question, or put a dismissed one back."""
    if status not in (GapStatus.OPEN, GapStatus.DISMISSED):
        raise InputRefused({"status": "Holat: open yoki dismissed."})
    row.status = status
    row.closed_at = now if status == GapStatus.DISMISSED else None
    db.flush()
    return row


def answer_gap(
    db: Session,
    *,
    row: AssistantGap,
    fields: dict[str, Any],
    now: datetime,
    actor: User,
    translate_from: str = "",
) -> HelpArticle:
    """Write the ready answer for a question: a published help article the
    assistant finds by the question's own words. A question that already
    has one gets it changed, not a second."""
    from app.modules.assistant.services.articles import save_article

    article = db.get(HelpArticle, row.article_id) if row.article_id else None
    # The question's own words find the answer, beside whatever the office
    # gave or the article already had.
    kept = str(fields.get("keywords") or (article.keywords if article else ""))
    words = [
        *(_line(part) for part in kept.split(",")),
        row.topic,
        *(_line(str(query)) for query in row.queries or ()),
    ]
    saved = save_article(
        db,
        fields={
            **fields,
            "keywords": ", ".join(dict.fromkeys(word for word in words if word)),
            "is_published": True,
        },
        now=now,
        row=article,
        actor=actor,
        translate_from=translate_from,
        commit=False,
    )
    row.article_id = saved.id
    row.status = GapStatus.ANSWERED
    row.closed_at = now
    db.flush()
    return saved


def release_article(db: Session, *, article_id: uuid.UUID) -> None:
    """An answer is being deleted: its questions wait for one again."""
    for row in db.scalars(
        select(AssistantGap).where(AssistantGap.article_id == article_id)
    ):
        row.article_id = None
        if row.status == GapStatus.ANSWERED:
            row.status, row.closed_at = GapStatus.OPEN, None
    db.flush()


__all__ = [
    "GapMissing",
    "answer_gap",
    "gap",
    "note_gap",
    "release_article",
    "set_status",
]
