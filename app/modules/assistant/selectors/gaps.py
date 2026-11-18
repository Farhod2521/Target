"""The unanswered questions as the office lists them."""

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.modules.assistant.constants import GAP_KIND_LABELS, GapStatus
from app.modules.assistant.models import AssistantGap, HelpArticle

PAGE_SIZE: Final = 50
OPEN: Final = "open"
CLOSED: Final = "closed"
TABS: Final[tuple[tuple[str, str], ...]] = (
    (OPEN, "Javob kutmoqda"),
    (CLOSED, "Yopilgan"),
)


@dataclass(frozen=True, slots=True)
class GapPage:
    rows: list[tuple[AssistantGap, HelpArticle | None]]
    total: int
    open: int
    offset: int
    next_offset: int
    has_more: bool


def _tab(query: Select[Any], tab: str) -> Select[Any]:
    if tab == CLOSED:
        return query.where(AssistantGap.status != GapStatus.OPEN)
    return query.where(AssistantGap.status == GapStatus.OPEN)


def _search(query: Select[Any], term: str) -> Select[Any]:
    term = term.strip()
    if not term:
        return query
    like = f"%{term}%"
    return query.where(
        or_(
            AssistantGap.topic.ilike(like),
            AssistantGap.missing.ilike(like),
            AssistantGap.question.ilike(like),
        )
    )


def open_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(AssistantGap)
            .where(AssistantGap.status == GapStatus.OPEN)
        )
        or 0
    )


def gaps(db: Session, *, tab: str, term: str, offset: int) -> GapPage:
    """What is asked most first; the closed ones by when they were closed."""
    query = _search(_tab(select(AssistantGap), tab), term)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    order = (
        (AssistantGap.closed_at.desc().nulls_last(), AssistantGap.hits.desc())
        if tab == CLOSED
        else (AssistantGap.hits.desc(), AssistantGap.last_asked_at.desc())
    )
    found = list(db.scalars(query.order_by(*order).offset(offset).limit(PAGE_SIZE)))
    ids = [row.article_id for row in found if row.article_id]
    articles = (
        {
            row.id: row
            for row in db.scalars(select(HelpArticle).where(HelpArticle.id.in_(ids)))
        }
        if ids
        else {}
    )
    next_offset = offset + len(found)
    return GapPage(
        rows=[(row, articles.get(row.article_id)) for row in found],
        total=total,
        open=open_count(db),
        offset=offset,
        next_offset=next_offset,
        has_more=next_offset < total,
    )


def gap_out(row: AssistantGap, article: HelpArticle | None) -> dict[str, Any]:
    from app.modules.assistant.services.articles import article_out

    return {
        "id": str(row.id),
        "topic": row.topic,
        "kind": row.kind,
        "kind_label": GAP_KIND_LABELS.get(row.kind, row.kind),
        "missing": row.missing,
        "question": row.question,
        "language": row.language,
        "queries": [str(query) for query in row.queries or ()],
        "samples": [
            {
                "question": str(item.get("question", "")),
                "at": str(item.get("at", "")),
                "owner_id": str(item.get("owner_id", "")),
            }
            for item in row.samples or ()
            if isinstance(item, dict)
        ],
        "hits": row.hits,
        "status": row.status,
        # Asked again after an answer was written for it.
        "reopened": row.status == GapStatus.OPEN and article is not None,
        "article": article_out(article) if article is not None else None,
        "created_at": row.created_at,
        "last_asked_at": row.last_asked_at,
        "closed_at": row.closed_at,
    }


__all__ = ["CLOSED", "OPEN", "TABS", "GapPage", "gap_out", "gaps", "open_count"]
