"""Which kinds of ticket each member of Support takes first.

A ticket's kind is the reason it came for (``TicketReason``). The Owner and
the superuser tick, per member, the kinds that member takes; a member with
nothing set takes every kind, and so does the Owner pressing «Zayavka
olish». A ticket with several open reasons is a member's when any of them
is one of their kinds; whoever takes it solves all of them. When none of a
member's kinds waits, «Zayavka olish» gives the oldest of any kind.
"""

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import ColumnElement, cast, delete, func, select
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH
from sqlalchemy.orm import Session

from app.common.exceptions import DomainError, NotFound
from app.modules.accounts.models import User
from app.modules.boards.constants import TICKET_REASON_LABELS, Board, TicketReason
from app.modules.boards.models import BoardCard, SupportKind

# In the order the settings show them.
ALL_KINDS: tuple[str, ...] = tuple(str(reason) for reason in TicketReason)


class NoKindChosen(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Kamida bitta zayavka turini belgilang.")


class UnknownKind(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Bunday zayavka turi yo'q.")


class NotSupportMember(NotFound):
    def __init__(self) -> None:
        super().__init__("Support xodimi topilmadi.")


def kinds_of(db: Session, *, member_id: uuid.UUID) -> frozenset[str] | None:
    """The member's kinds; None: every kind."""
    rows = db.scalars(
        select(SupportKind.reason).where(SupportKind.member_id == member_id)
    ).all()
    return frozenset(rows) if rows else None


def has_kind(kinds: Iterable[str]) -> ColumnElement[bool]:
    """A ticket with one of ``kinds`` still open on it."""
    return func.jsonb_path_exists(
        BoardCard.reasons,
        cast("$[*] ? (!exists(@.solved_at) && @.code == $codes[*])", JSONPATH),
        cast({"codes": sorted(kinds)}, JSONB),
    )


def set_kinds(
    db: Session, *, member_id: uuid.UUID, kinds: list[str], actor: User
) -> frozenset[str] | None:
    """Save the member's kinds. Every kind ticked is stored as nothing set,
    so a kind added later reaches them too. The caller commits."""
    from app.modules.boards.access import works_on

    member = db.get(User, member_id)
    if (
        member is None
        or not member.is_active
        or not works_on(db, member, Board.SUPPORT)
    ):
        raise NotSupportMember
    chosen = set(kinds)
    if not chosen:
        raise NoKindChosen
    if not chosen <= set(ALL_KINDS):
        raise UnknownKind
    db.execute(delete(SupportKind).where(SupportKind.member_id == member_id))
    if chosen != set(ALL_KINDS):
        db.add_all(
            SupportKind(member_id=member_id, reason=reason, set_by_id=actor.id)
            for reason in ALL_KINDS
            if reason in chosen
        )
    db.flush()
    return kinds_of(db, member_id=member_id)


def _member(db: Session, person: User) -> dict[str, Any]:
    kinds = kinds_of(db, member_id=person.id)
    return {
        "id": str(person.id),
        "name": person.full_name or person.email,
        "email": person.email,
        "kinds": [kind for kind in ALL_KINDS if kinds is None or kind in kinds],
        "all": kinds is None,
    }


def kinds_view(db: Session) -> dict[str, Any]:
    """The settings: every kind with its name, and each member of Support
    with the kinds they take."""
    from app.modules.boards.view import board_staff

    people = [
        db.get(User, uuid.UUID(p["id"])) for p in board_staff(db, board=Board.SUPPORT)
    ]
    return {
        "kinds": [
            {"value": kind, "label": str(TICKET_REASON_LABELS[TicketReason(kind)])}
            for kind in ALL_KINDS
        ],
        "members": [_member(db, person) for person in people if person is not None],
    }


def member_view(db: Session, *, member_id: uuid.UUID) -> dict[str, Any]:
    person = db.get(User, member_id)
    if person is None:
        raise NotSupportMember
    return _member(db, person)
