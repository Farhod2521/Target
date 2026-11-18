"""What each member of Support did, day by day: how many clients they
talked to, how many tickets they took and called solved, and what the
clients answered.

A client was talked to on a day when the member wrote in their support chat
that day, or on their ticket wrote a note, waited for them, gave it to a
developer or called it solved. Taking a ticket, giving it up or not
reaching the client is not talking. «Hal qilindi» is the member's
press; the client's yes or no that follows has no person of its own and
counts for whoever pressed the «Hal qilindi» before it. Calls are not
counted yet. Days are the office's (Tashkent). A member reads their own
line; the Owner and the superuser read everybody's.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.modules.accounts.models import User
from app.modules.boards.access import Access
from app.modules.boards.constants import REPORT_MAX_DAYS, Board, EventKind
from app.modules.boards.exceptions import ReportPeriodInvalid
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.renewal import day_bounds

# The client's own answers: they count for whoever pressed «Hal qilindi».
_BY_CLIENT = (EventKind.CONFIRMED, EventKind.DENIED)
# Ticket work that means the member was in touch with the client.
_TALKS = frozenset(
    {
        str(EventKind.NOTE),
        str(EventKind.WAITING),
        str(EventKind.DEVELOPER),
        str(EventKind.RESOLVED),
    }
)
FIELDS = ("talked", "messages", "taken", "solved", "confirmed", "denied")


@dataclass
class _Day:
    clients: set[uuid.UUID] = field(default_factory=set)
    messages: int = 0
    taken: int = 0
    solved: int = 0
    confirmed: int = 0
    denied: int = 0

    def line(self) -> dict[str, int]:
        return {
            "talked": len(self.clients),
            "messages": self.messages,
            "taken": self.taken,
            "solved": self.solved,
            "confirmed": self.confirmed,
            "denied": self.denied,
        }


def _sum(days: dict[date, _Day]) -> _Day:
    out = _Day()
    for day in days.values():
        out.clients |= day.clients
        out.messages += day.messages
        out.taken += day.taken
        out.solved += day.solved
        out.confirmed += day.confirmed
        out.denied += day.denied
    return out


def _who_solved(
    db: Session, events: list[tuple[uuid.UUID, datetime]]
) -> list[uuid.UUID | None]:
    """For each client's answer (card, when), who pressed the «Hal qilindi»
    it answers: the latest before it on that card."""
    cards = {card_id for card_id, _ in events}
    if not cards:
        return []
    presses: dict[uuid.UUID, list[tuple[datetime, uuid.UUID | None]]] = defaultdict(
        list
    )
    for card_id, at, actor in db.execute(
        select(
            BoardCardEvent.card_id, BoardCardEvent.created_at, BoardCardEvent.actor_id
        )
        .where(
            BoardCardEvent.card_id.in_(cards),
            BoardCardEvent.kind == str(EventKind.RESOLVED),
        )
        .order_by(BoardCardEvent.created_at)
    ):
        presses[card_id].append((at, actor))
    out: list[uuid.UUID | None] = []
    for card_id, at in events:
        before = [actor for pressed, actor in presses[card_id] if pressed <= at]
        out.append(before[-1] if before else None)
    return out


def report(
    db: Session, *, user: User, access: Access, start: date, end: date
) -> dict[str, Any]:
    from app.modules.supportchat.models import SupportMessage

    if end < start or (end - start).days > REPORT_MAX_DAYS:
        raise ReportPeriodInvalid
    first, after = day_bounds(start, end)
    everybody = access.leads_board(Board.SUPPORT)
    by: dict[uuid.UUID, dict[date, _Day]] = defaultdict(lambda: defaultdict(_Day))

    def day_of(at: datetime) -> date:
        return localtime(at).date()

    events = select(
        BoardCardEvent.actor_id,
        BoardCardEvent.owner_id,
        BoardCardEvent.kind,
        BoardCardEvent.created_at,
        BoardCardEvent.card_id,
    ).where(
        BoardCardEvent.created_at >= first,
        BoardCardEvent.created_at < after,
        # Only the lines the report counts are read.
        BoardCardEvent.kind.in_(
            [*_TALKS, str(EventKind.TICKET_TAKEN), *(str(k) for k in _BY_CLIENT)]
        ),
        BoardCardEvent.card_id.in_(
            select(BoardCard.id).where(BoardCard.board == str(Board.SUPPORT))
        ),
    )
    answers: list[tuple[uuid.UUID, datetime, str]] = []
    for actor, owner, kind, at, card_id in db.execute(events):
        if kind in _BY_CLIENT:
            answers.append((card_id, at, kind))
            continue
        if actor is None or (not everybody and actor != user.id):
            continue
        # Only what the report counts makes a line: a hand that only moved
        # or gave tickets (the Owner) or fixed one (a Developer) is not Support's work.
        if kind not in _TALKS and kind != EventKind.TICKET_TAKEN:
            continue
        day = by[actor][day_of(at)]
        if kind in _TALKS:
            day.clients.add(owner)
        if kind == EventKind.TICKET_TAKEN:
            day.taken += 1
        elif kind == EventKind.RESOLVED:
            day.solved += 1
    for (_card, at, kind), solver in zip(
        answers, _who_solved(db, [(c, a) for c, a, _ in answers]), strict=True
    ):
        if solver is None or (not everybody and solver != user.id):
            continue
        day = by[solver][day_of(at)]
        if kind == EventKind.CONFIRMED:
            day.confirmed += 1
        else:
            day.denied += 1

    chat = select(
        SupportMessage.sender_id, SupportMessage.owner_id, SupportMessage.created_at
    ).where(
        SupportMessage.created_at >= first,
        SupportMessage.created_at < after,
        SupportMessage.deleted_at.is_(None),
        SupportMessage.sender_id.is_not(None),
        SupportMessage.sender_id != SupportMessage.owner_id,
    )
    if not everybody:
        chat = chat.where(SupportMessage.sender_id == user.id)
    for sender, owner, at in db.execute(chat):
        assert sender is not None
        day = by[sender][day_of(at)]
        day.clients.add(owner)
        day.messages += 1

    return _shape(db, by, user=user, everybody=everybody, start=start, end=end)


def _shape(
    db: Session,
    by: dict[uuid.UUID, dict[date, _Day]],
    *,
    user: User,
    everybody: bool,
    start: date,
    end: date,
) -> dict[str, Any]:
    from app.modules.boards.view import board_staff

    if everybody:
        ids = [uuid.UUID(p["id"]) for p in board_staff(db, board=Board.SUPPORT)]
        # Somebody off the team who worked tickets (the Owner) is listed too.
        ids += [member for member in by if member not in ids]
    else:
        ids = [user.id]
    people = {p.id: p for p in db.scalars(select(User).where(User.id.in_(ids)))}
    members: list[dict[str, Any]] = []
    overall = _Day()
    for member in ids:
        person = people.get(member)
        if person is None:
            continue
        days = by.get(member, {})
        total = _sum(days)
        overall.clients |= total.clients
        for name in FIELDS[1:]:
            setattr(overall, name, getattr(overall, name) + getattr(total, name))
        members.append(
            {
                "id": str(member),
                "name": person.full_name or person.email,
                "email": person.email,
                "total": total.line(),
                "days": [
                    {"day": day, **days[day].line()}
                    for day in sorted(days, reverse=True)
                ],
            }
        )
    members.sort(
        key=lambda m: (-m["total"]["solved"], -m["total"]["talked"], m["name"])
    )
    return {
        "date_from": start,
        "date_to": end,
        "total": overall.line(),
        "members": members,
    }
