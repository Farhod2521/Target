"""The clients' word on the assistant's answers, as the office lists it."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.assistant.constants import (
    RATING_DOWN,
    RATING_REASONS,
    RATING_UP,
    FeedbackKind,
    FeedbackStatus,
)
from app.modules.assistant.models import AssistantFeedback

PAGE_SIZE: Final = 50
OPEN: Final = "open"
DONE: Final = "done"
# Which words: both kinds, only 👎, or only those asked before a request.
KIND_ALL: Final = ""
KIND_DOWN: Final = "down"
KIND_TICKET: Final = "ticket"
WEEK: Final = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class Ratings:
    up: int
    down: int


@dataclass(frozen=True, slots=True)
class RatingCounts:
    """👍 and 👎 today and over the last seven days, for the office's line."""

    today: Ratings
    week: Ratings


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


def _kind(query: Select[Any], kind: str) -> Select[Any]:
    """A 👍 is only counted: it is never a row to read."""
    down = (AssistantFeedback.kind == FeedbackKind.RATING) & (
        AssistantFeedback.rating == RATING_DOWN
    )
    if kind == KIND_DOWN:
        return query.where(down)
    if kind == KIND_TICKET:
        return query.where(AssistantFeedback.kind == FeedbackKind.TICKET)
    return query.where((AssistantFeedback.kind == FeedbackKind.TICKET) | down)


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


def rating_counts(db: Session, *, now: datetime) -> RatingCounts:
    def counted(since: datetime) -> Ratings:
        rows = dict(
            db.execute(
                select(AssistantFeedback.rating, func.count())
                .where(
                    AssistantFeedback.kind == FeedbackKind.RATING,
                    AssistantFeedback.updated_at >= since,
                )
                .group_by(AssistantFeedback.rating)
            ).all()
        )
        return Ratings(
            up=int(rows.get(RATING_UP, 0)), down=int(rows.get(RATING_DOWN, 0))
        )

    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return RatingCounts(today=counted(midnight), week=counted(now - WEEK))


def feedback_page(
    db: Session, *, tab: str, term: str, offset: int, kind: str = KIND_ALL
) -> FeedbackPage:
    """Newest first: a word on the answers is read while it is fresh."""
    query = _search(_kind(_tab(select(AssistantFeedback), tab), kind), term)
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
        "kind": row.kind,
        "rating": row.rating,
        "reason": row.reason,
        "reason_label": RATING_REASONS.get(row.reason, ""),
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
