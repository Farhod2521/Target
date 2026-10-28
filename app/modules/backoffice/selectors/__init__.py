"""What every office screen reads first: the rail, the journal, a card's traces."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session, joinedload

from app.modules.accounts.models import User
from app.modules.backoffice.constants import (
    ACTION_KIND_LABELS,
    ADMIN_ROLES,
    ANSWER_ROLES,
    CARD_TRACES,
    FEEDBACK_ROLES,
    JOURNAL_PAGE,
    MONEY_ROLES,
    READ_KINDS,
    ROLE_LABELS,
    SALES_LEAD_ROLES,
    SALES_ROLES,
    WRITE_KINDS,
    ActionKind,
    Role,
)
from app.modules.backoffice.models import StaffAction
from app.modules.backoffice.permissions import roles_of
from app.modules.billing.constants import RedemptionStatus
from app.modules.billing.models import PromoRedemption
from app.modules.referrals.constants import FeedbackStatus, PayoutStatus
from app.modules.referrals.models import Feedback, WithdrawalRequest
from app.modules.sales.selectors import waiting_ariza_count
from app.modules.supportchat.selectors import awaiting_reply_count


def _count(db: Session, model: Any, where: ColumnElement[bool]) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(where)) or 0)


def waiting_promo_count(db: Session) -> int:
    return _count(
        db, PromoRedemption, PromoRedemption.status == RedemptionStatus.PENDING
    )


def waiting_ask_count(db: Session) -> int:
    return _count(
        db, WithdrawalRequest, WithdrawalRequest.status == PayoutStatus.REQUESTED
    )


def waiting_feedback_count(db: Session) -> int:
    return _count(db, Feedback, Feedback.status == FeedbackStatus.PENDING)


@dataclass(frozen=True, slots=True)
class Shell:
    """Which doors this reader may open, and what waits behind them.

    A door they may not open is absent, not disabled, as in Django: a
    count is read only for the roles that answer it.
    """

    roles: frozenset[str]
    is_superuser: bool
    can_give: bool
    can_grant: bool
    is_owner: bool
    is_engineer: bool
    can_answer: bool
    may_answer_feedback: bool
    can_sell: bool
    leads_sales: bool
    waiting_promos: int
    waiting_asks: int
    waiting_feedback: int
    waiting_support: int
    waiting_arizas: int


def office_shell(db: Session, *, user: User, now: datetime) -> Shell:
    held = roles_of(db, user)

    def holds(roles: tuple[Role, ...]) -> bool:
        return bool(held & {str(role) for role in roles})

    can_give = holds(ADMIN_ROLES)
    can_answer = holds(ANSWER_ROLES)
    may_answer_feedback = user.is_superuser or holds(FEEDBACK_ROLES)
    can_sell = holds(SALES_ROLES)
    return Shell(
        roles=held,
        is_superuser=user.is_superuser,
        can_give=can_give,
        can_grant=holds(MONEY_ROLES),
        is_owner=str(Role.OWNER) in held,
        is_engineer=str(Role.ENGINEER) in held,
        can_answer=can_answer,
        may_answer_feedback=may_answer_feedback,
        can_sell=can_sell,
        leads_sales=holds(SALES_LEAD_ROLES),
        waiting_promos=waiting_promo_count(db) if can_give else 0,
        waiting_asks=waiting_ask_count(db) if can_give else 0,
        waiting_feedback=waiting_feedback_count(db) if may_answer_feedback else 0,
        waiting_support=awaiting_reply_count(db) if can_answer else 0,
        waiting_arizas=waiting_ariza_count(db, now=now) if can_sell else 0,
    )


def role_choices() -> list[tuple[str, str]]:
    return [(str(role), str(ROLE_LABELS[role])) for role in Role]


@dataclass(frozen=True, slots=True)
class JournalPage:
    rows: list[StaffAction]
    offset: int
    has_more: bool

    @property
    def next_offset(self) -> int:
        return self.offset + len(self.rows)


def journal(db: Session, *, kind: str = "", offset: int = 0) -> JournalPage:
    """The office's own log, newest first: writes only, unless a kind is named."""
    rows = select(StaffAction).options(
        joinedload(StaffAction.owner), joinedload(StaffAction.actor)
    )
    rows = rows.where(
        StaffAction.kind == kind
        if kind
        else StaffAction.kind.in_([str(k) for k in WRITE_KINDS])
    )
    window = list(
        db.scalars(
            rows.order_by(StaffAction.created_at.desc())
            .offset(offset)
            .limit(JOURNAL_PAGE + 1)
        )
    )
    return JournalPage(
        rows=window[:JOURNAL_PAGE], offset=offset, has_more=len(window) > JOURNAL_PAGE
    )


def kind_choices() -> list[tuple[str, str]]:
    """The journal's chips: everything done, each write, then the readings."""
    return [
        ("", "Amallar"),
        *((str(kind), str(ACTION_KIND_LABELS[kind])) for kind in WRITE_KINDS),
        *((str(kind), str(ACTION_KIND_LABELS[kind])) for kind in READ_KINDS),
    ]


def kind_label(kind: str) -> str:
    try:
        return str(ACTION_KIND_LABELS[ActionKind(kind)])
    except ValueError:
        return kind


def traces(db: Session, *, owner: User) -> list[StaffAction]:
    """What the office did to one account, readings included, newest first."""
    return list(
        db.scalars(
            select(StaffAction)
            .options(joinedload(StaffAction.actor))
            .where(StaffAction.owner_id == owner.id)
            .order_by(StaffAction.created_at.desc())
            .limit(CARD_TRACES)
        )
    )


__all__ = [
    "JournalPage",
    "Shell",
    "journal",
    "kind_choices",
    "kind_label",
    "office_shell",
    "role_choices",
    "traces",
    "waiting_ask_count",
    "waiting_feedback_count",
    "waiting_promo_count",
]
