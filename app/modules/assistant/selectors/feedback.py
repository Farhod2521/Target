"""The clients' word on the assistant's answers, as the office lists it."""

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.assistant.constants import FeedbackStatus
from app.modules.assistant.models import AssistantFeedback

PAGE_SIZE: Final = 50
OPEN: Final = "open"
DONE: Final = "done"


@dataclass(frozen=True, slots=True)
class FeedbackPage:
    rows: list[tuple[AssistantFeedback, User | None]]
    total: int
    open: int
    offset: int
    next_offset: int
    has_more: bool


def _tab(query: Select[Any], tab: str) -> Select[Any]:
    status = FeedbackStatus.DONE if tab == DONE else FeedbackStatus.OPEN
    return query.where(AssistantFeedback.status == status)


def _search(query: Select[Any], term: str) -> Select[Any]:
    term = term.strip()
    if not term:
        return query
    like = f"%{term}%"
    return query.where(
        or_(
            AssistantFeedback.feedback.ilike(like),
            AssistantFeedback.question.ilike(like),
            AssistantFeedback.answer.ilike(like),
        )
    )


def open_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(AssistantFeedback)
            .where(AssistantFeedback.status == FeedbackStatus.OPEN)
        )
        or 0
    )


def feedback_page(db: Session, *, tab: str, term: str, offset: int) -> FeedbackPage:
    """Newest first: a word on the answers is read while it is fresh."""
    query = _search(_tab(select(AssistantFeedback), tab), term)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    found = list(
        db.scalars(
            query.order_by(AssistantFeedback.created_at.desc())
            .offset(offset)
            .limit(PAGE_SIZE)
        )
    )
    owners = (
        {
            row.id: row
            for row in db.scalars(
                select(User).where(User.id.in_({row.owner_id for row in found}))
            )
        }
        if found
        else {}
    )
    next_offset = offset + len(found)
    return FeedbackPage(
        rows=[(row, owners.get(row.owner_id)) for row in found],
        total=total,
        open=open_count(db),
        offset=offset,
        next_offset=next_offset,
        has_more=next_offset < total,
    )


def feedback_out(row: AssistantFeedback, owner: User | None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "owner": (
            {
                "id": str(owner.id),
                "name": owner.full_name or "",
                "email": owner.email or "",
                "phone": owner.phone or "",
            }
            if owner is not None
            else None
        ),
        "question": row.question,
        "answer": row.answer,
        "ticket_summary": row.ticket_summary,
        "feedback": row.feedback,
        "language": row.language,
        "status": row.status,
        "created_at": row.created_at,
        "closed_at": row.closed_at,
    }


__all__ = [
    "DONE",
    "OPEN",
    "FeedbackPage",
    "feedback_out",
    "feedback_page",
    "open_count",
]
