"""Reads over what the agent has proposed. Every one of them scopes by owner first."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, Select, and_, false, not_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.modules.accounts.models import User
from app.modules.ads.constants import NOT_LIVE
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.agent.constants import (
    IN_FLIGHT_MINUTES,
    OPEN_STATUSES,
    RECENT_DECIDED,
    RECENT_OUTCOMES,
    SuggestionKind,
    SuggestionStatus,
)
from app.modules.agent.models import AgentSuggestion
from app.modules.audit.constants import ActionStatus
from app.modules.audit.models import ActionLog

_LIVE = (ActionStatus.PENDING, ActionStatus.APPLIED)
S = AgentSuggestion


def outside(scope: PageScope) -> ColumnElement[bool]:
    """The proposals whose object is known to be on another page."""
    return or_(
        and_(S.target_level == "adset", S.target_external_id.in_(scope.outside)),
        and_(S.target_level == "ad", S.target_parent_id.in_(scope.outside)),
        and_(S.target_level == "campaign", S.target_external_id.in_(scope.blocked)),
        and_(S.target_level == "page", S.target_external_id.not_in(list(scope.pages))),
    )


def switched_off(owner: User) -> ColumnElement[bool]:
    """The proposals whose object, or the group above it, is switched off."""
    off_groups = select(AdSet.external_id).where(
        AdSet.owner_id == owner.id, AdSet.delivery.in_(NOT_LIVE)
    )
    off_ads = select(Ad.external_id).where(
        Ad.owner_id == owner.id, Ad.delivery.in_(NOT_LIVE)
    )
    off_campaigns = select(Campaign.external_id).where(
        Campaign.owner_id == owner.id, Campaign.delivery.in_(NOT_LIVE)
    )
    return and_(
        or_(
            and_(S.target_level == "adset", S.target_external_id.in_(off_groups)),
            and_(S.target_level == "ad", S.target_parent_id.in_(off_groups)),
            and_(S.target_level == "ad", S.target_external_id.in_(off_ads)),
            and_(
                S.target_level == "campaign",
                S.target_external_id.in_(off_campaigns),
            ),
        ),
        S.kind != SuggestionKind.RESUME,
    )


def _elsewhere(scope: PageScope | None) -> ColumnElement[bool]:
    return false() if scope is None else outside(scope)


def _owned(owner: User) -> Select[tuple[AgentSuggestion]]:
    return select(S).where(S.owner_id == owner.id)


def _asking(owner: User, now: datetime) -> Select[tuple[AgentSuggestion]]:
    return _owned(owner).where(
        S.status == SuggestionStatus.PENDING,
        S.expires_at > now,
        not_(switched_off(owner)),
    )


def waiting(
    db: Session, *, owner: User, now: datetime, scope: PageScope | None = None
) -> list[AgentSuggestion]:
    """What is being asked right now, dearest first."""
    return list(
        db.scalars(
            _asking(owner, now)
            .where(not_(_elsewhere(scope)))
            .options(selectinload(S.run))
            .order_by(S.weight.desc(), S.created_at.desc())
        )
    )


def unanswered(
    db: Session, *, owner: User, now: datetime, scope: PageScope | None = None
) -> list[AgentSuggestion]:
    """Open proposals whose window has passed. Still executable, any time."""
    return list(
        db.scalars(
            _owned(owner)
            .where(
                or_(
                    S.status == SuggestionStatus.UNANSWERED,
                    and_(S.status == SuggestionStatus.PENDING, S.expires_at <= now),
                ),
                not_(_elsewhere(scope)),
                not_(switched_off(owner)),
            )
            .options(selectinload(S.run))
            .order_by(S.weight.desc(), S.created_at.desc())
        )
    )


def waiting_count(
    db: Session, *, owner: User, now: datetime, scope: PageScope | None = None
) -> int:
    """How many answers are outstanding - the badge on the navigation."""
    from sqlalchemy import func

    query = _asking(owner, now).where(not_(_elsewhere(scope)))
    return db.scalar(select(func.count()).select_from(query.subquery())) or 0


def decided(
    db: Session,
    *,
    owner: User,
    limit: int = RECENT_DECIDED,
    before: datetime | None = None,
    scope: PageScope | None = None,
) -> list[AgentSuggestion]:
    """Proposals that are no longer open, newest first."""
    query = (
        _owned(owner)
        .where(S.status.not_in(OPEN_STATUSES), not_(_elsewhere(scope)))
        .options(selectinload(S.action_log), selectinload(S.decided_by))
        .order_by(S.decided_at.desc(), S.created_at.desc())
    )
    if before is not None:
        query = query.where(
            or_(
                S.decided_at < before,
                and_(S.decided_at.is_(None), S.created_at < before),
            )
        )
    return list(db.scalars(query.limit(limit)))


def recently_assessed(
    db: Session,
    *,
    owner: User,
    since: datetime,
    limit: int | None = RECENT_OUTCOMES,
    scope: PageScope | None = None,
) -> list[AgentSuggestion]:
    """Changes whose verdict was written since ``since``, newest first."""
    query = (
        _owned(owner)
        .where(
            S.status == SuggestionStatus.APPROVED,
            S.assessed_at >= since,
            S.outcome != "",
            not_(_elsewhere(scope)),
        )
        .order_by(S.assessed_at.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    return list(db.scalars(query))


def _in_flight(owner: User, now: datetime) -> Select[tuple[AgentSuggestion]]:
    return (
        _owned(owner)
        .join(ActionLog, ActionLog.id == S.action_log_id)
        .where(
            S.status == SuggestionStatus.APPROVED,
            ActionLog.status == ActionStatus.PENDING,
            ActionLog.created_at >= now - timedelta(minutes=IN_FLIGHT_MINUTES),
        )
    )


def working(db: Session, *, owner: User, now: datetime) -> bool:
    """Whether a change somebody approved is still on its way to the provider."""
    return db.scalar(_in_flight(owner, now).limit(1)) is not None


def is_working(db: Session, *, owner: User, pk: str, now: datetime) -> bool:
    """The same question as :func:`working`, about one proposal."""
    key = _uuid(pk)
    if key is None:
        return False
    return db.scalar(_in_flight(owner, now).where(S.id == key).limit(1)) is not None


def one(db: Session, *, owner: User, pk: str | uuid.UUID) -> AgentSuggestion | None:
    """A single proposal belonging to this owner, or nothing."""
    key = pk if isinstance(pk, uuid.UUID) else _uuid(pk)
    if key is None:
        return None
    return db.scalar(_owned(owner).where(S.id == key))


def _uuid(raw: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def blocked_targets(db: Session, *, owner: User, since: datetime) -> set[str]:
    """Objects the agent must leave alone tonight."""
    touched = set(
        db.scalars(
            select(ActionLog.target_external_id).where(
                ActionLog.owner_id == owner.id,
                ActionLog.created_at >= since,
                ActionLog.status.in_(_LIVE),
            )
        )
    )
    proposed = set(
        db.scalars(
            select(S.target_external_id).where(
                S.owner_id == owner.id, S.status == SuggestionStatus.PENDING
            )
        )
    )
    return touched | proposed


def refused_targets(
    db: Session, *, owner: User, since: datetime
) -> set[tuple[str, str]]:
    """``(rule, object)`` pairs the owner recently said no to."""
    return {
        (rule, target)
        for rule, target in db.execute(
            select(S.rule, S.target_external_id).where(
                S.owner_id == owner.id,
                S.status == SuggestionStatus.REJECTED,
                S.decided_at >= since,
            )
        )
    }


def _due(now: datetime) -> ColumnElement[bool]:
    return and_(
        S.status == SuggestionStatus.APPROVED,
        S.outcome == "",
        S.review_at.is_not(None),
        S.review_at <= now,
    )


def due_for_assessment(
    db: Session, *, owner: User, now: datetime
) -> list[AgentSuggestion]:
    """Approved changes whose aftermath is now old enough to read."""
    return list(db.scalars(_owned(owner).where(_due(now))))


def owners_with_outcomes_due(db: Session, *, now: datetime) -> list[str]:
    """Every owner with an approved change whose aftermath can be read now."""
    return [
        str(owner_id)
        for owner_id in db.scalars(select(S.owner_id).where(_due(now)).distinct())
    ]


def suggestions_about(
    db: Session, *, owner: User, external_ids: list[str]
) -> tuple[AgentSuggestion, ...]:
    """Every proposal ever made about these objects, newest first."""
    if not external_ids:
        return ()
    return tuple(
        db.scalars(
            _owned(owner)
            .where(S.target_external_id.in_(external_ids))
            .options(selectinload(S.decided_by))
            .order_by(S.created_at.desc())
        )
    )


__all__ = [
    "blocked_targets",
    "decided",
    "due_for_assessment",
    "is_working",
    "one",
    "outside",
    "owners_with_outcomes_due",
    "recently_assessed",
    "refused_targets",
    "suggestions_about",
    "switched_off",
    "unanswered",
    "waiting",
    "waiting_count",
    "working",
]
