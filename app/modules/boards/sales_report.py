"""The Sales board's report: what the period brought, day by day and person
by person. Every figure is read from the board's own history lines, so a
day once over never changes when it is read again.

- Yangi lid: cards opened (a sign-up became a lead) that day.
- Olindi: «Lid olish» pressed, or the lead gave a card to somebody.
- Gaplashildi / Bog'lanilmadi / Qayta aloqa: the buttons pressed.
- Sotildi: the first full plan paid (Start is not a sale); the money is
  that bill's. A sale is the card's manager's; nobody's when the client paid
  before anybody took them.
- Yopildi: closed by a person, or by the discount running out.
- Qo'ng'iroqlar: the exchange's calls by the staff member, when it is tied.
- Birinchi aloqa: from «Lid olish» to the first call button pressed.

A manager reads their own figures only; the Sales lead, the Owner and the
superuser read everybody's.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from statistics import median
from typing import Any

from sqlalchemy import Date, cast, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, aliased

from app.common.config import settings
from app.common.dates import localtime, office_zone
from app.common.db import utcnow
from app.modules.accounts.constants import SIGNUP_VIA_LABELS, SignupVia
from app.modules.accounts.models import User
from app.modules.billing.constants import InvoiceKind, InvoiceStatus
from app.modules.billing.models import Invoice
from app.modules.boards.access import Access, works_on
from app.modules.boards.constants import (
    CLOSE_REASON_LABELS,
    OFFER_ENDED_LABEL,
    OFFER_ENDED_REASON,
    REPORT_MAX_DAYS,
    Board,
    CloseReason,
    EventKind,
    SalesColumn,
)
from app.modules.boards.exceptions import ReportPeriodInvalid
from app.modules.boards.models import BoardCard, BoardCardEvent

BOARD = str(Board.SALES)
# Who a figure belongs to when nobody did it: a client who paid alone.
NOBODY = "none"

_TAKEN = (str(EventKind.TAKEN), str(EventKind.ASSIGNED))
_CALLED = (
    str(EventKind.CONTACTED),
    str(EventKind.NO_CONTACT),
    str(EventKind.CALLBACK),
)
_COUNTED = {
    str(EventKind.CONTACTED): "contacted",
    str(EventKind.NO_CONTACT): "no_contact",
    str(EventKind.CALLBACK): "callbacks",
}


@dataclass(slots=True)
class Figures:
    leads: int = 0
    taken: int = 0
    contacted: int = 0
    no_contact: int = 0
    callbacks: int = 0
    sold: int = 0
    sold_offer: int = 0
    closed: int = 0
    calls: int = 0
    calls_answered: int = 0
    talk_seconds: int = 0
    money: dict[str, int] = field(default_factory=dict)
    first_touch: list[float] = field(default_factory=list)

    def add(self, other: "Figures") -> None:
        for name in (
            "leads",
            "taken",
            "contacted",
            "no_contact",
            "callbacks",
            "sold",
            "sold_offer",
            "closed",
            "calls",
            "calls_answered",
            "talk_seconds",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        for currency, minor in other.money.items():
            self.money[currency] = self.money.get(currency, 0) + minor
        self.first_touch.extend(other.first_touch)

    def out(self, *, rate_base: int) -> dict[str, Any]:
        return {
            "leads": self.leads,
            "taken": self.taken,
            "contacted": self.contacted,
            "no_contact": self.no_contact,
            "callbacks": self.callbacks,
            "sold": self.sold,
            "sold_offer": self.sold_offer,
            "closed": self.closed,
            "rate": round(self.sold * 100 / rate_base) if rate_base else 0,
            "calls": self.calls,
            "calls_answered": self.calls_answered,
            "talk_seconds": self.talk_seconds,
            "money": [
                {"currency": currency, "minor": minor}
                for currency, minor in sorted(self.money.items(), key=lambda m: -m[1])
            ],
            "first_touch_minutes": round(median(self.first_touch))
            if self.first_touch
            else None,
        }


def _day(column: Any) -> Any:
    """The office day a moment fell on, in the database."""
    # Written into the statement, not bound: GROUP BY must read the very
    # same expression as the select, and two bound copies are two to PG.
    zone = literal_column("'" + settings.office_timezone.replace("'", "''") + "'")
    return cast(func.timezone(zone, column), Date)


def day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    zone = office_zone()
    first = datetime.combine(start, time.min, zone)
    return first, datetime.combine(end, time.min, zone) + timedelta(days=1)


def _key(person: uuid.UUID | None) -> str:
    return str(person) if person else NOBODY


def _first_paid() -> Any:
    """Each client's first full plan bill: the sale's money."""
    from app.modules.boards.triggers import _full_plans

    return (
        select(
            Invoice.owner_id,
            Invoice.amount_minor,
            Invoice.currency,
        )
        .where(
            Invoice.status == str(InvoiceStatus.PAID),
            Invoice.kind == str(InvoiceKind.PLAN),
            Invoice.plan_id.in_(_full_plans()),
        )
        .ext(distinct_on(Invoice.owner_id))
        .order_by(Invoice.owner_id, Invoice.paid_at, Invoice.id)
        .subquery()
    )


def report(
    db: Session, *, user: User, access: Access, start: date, end: date
) -> dict[str, Any]:
    if end < start or (end - start).days > REPORT_MAX_DAYS:
        raise ReportPeriodInvalid
    first, after = day_bounds(start, end)
    lead = access.leads_board(Board.SALES)
    cells: dict[tuple[str, date], Figures] = defaultdict(Figures)
    reasons: dict[str, dict[str, int]] = defaultdict(dict)

    # Yangi lid: nobody's; the lead's view only.
    for day, total in db.execute(
        select(_day(BoardCard.opened_at), func.count())
        .where(
            BoardCard.board == BOARD,
            BoardCard.opened_at >= first,
            BoardCard.opened_at < after,
        )
        .group_by(_day(BoardCard.opened_at))
    ):
        cells[(NOBODY, day)].leads += int(total)

    # Olindi: «Lid olish» is its presser's; a card given is its new manager's.
    # The given one's line names the manager only in words, so the card's
    # manager now stands for them.
    for kind, actor, manager, day in db.execute(
        select(
            BoardCardEvent.kind,
            BoardCardEvent.actor_id,
            BoardCard.manager_id,
            _day(BoardCardEvent.created_at),
        )
        .join(BoardCard, BoardCard.id == BoardCardEvent.card_id)
        .where(
            BoardCard.board == BOARD,
            BoardCardEvent.kind.in_(_TAKEN),
            BoardCardEvent.created_at >= first,
            BoardCardEvent.created_at < after,
        )
    ):
        person = actor if kind == EventKind.TAKEN else manager
        cells[(_key(person), day)].taken += 1

    # The call buttons: their presser's.
    for kind, actor, day, total in db.execute(
        select(
            BoardCardEvent.kind,
            BoardCardEvent.actor_id,
            _day(BoardCardEvent.created_at),
            func.count(),
        )
        .join(BoardCard, BoardCard.id == BoardCardEvent.card_id)
        .where(
            BoardCard.board == BOARD,
            BoardCardEvent.kind.in_(_CALLED),
            BoardCardEvent.created_at >= first,
            BoardCardEvent.created_at < after,
        )
        .group_by(
            BoardCardEvent.kind,
            BoardCardEvent.actor_id,
            _day(BoardCardEvent.created_at),
        )
    ):
        cell = cells[(_key(actor), day)]
        name = _COUNTED[kind]
        setattr(cell, name, getattr(cell, name) + int(total))

    # Sotildi, with the bill's money and whether a discount ran.
    paid = _first_paid()
    offered = (
        select(BoardCardEvent.card_id)
        .where(
            BoardCardEvent.kind.in_(
                (str(EventKind.OFFERED), str(EventKind.START_BOUGHT))
            )
        )
        .scalar_subquery()
    )
    for manager, day, currency, minor, with_offer in db.execute(
        select(
            BoardCard.manager_id,
            _day(BoardCardEvent.created_at),
            paid.c.currency,
            paid.c.amount_minor,
            BoardCard.id.in_(offered),
        )
        .join(BoardCard, BoardCard.id == BoardCardEvent.card_id)
        .outerjoin(paid, paid.c.owner_id == BoardCard.owner_id)
        .where(
            BoardCard.board == BOARD,
            BoardCardEvent.kind == str(EventKind.SOLD),
            BoardCardEvent.created_at >= first,
            BoardCardEvent.created_at < after,
            # A card the Owner moved out of Sotildi afterwards is no sale.
            BoardCard.column_code == str(SalesColumn.SOLD),
        )
    ):
        cell = cells[(_key(manager), day)]
        cell.sold += 1
        cell.sold_offer += 1 if with_offer else 0
        if currency and minor:
            cell.money[currency] = cell.money.get(currency, 0) + int(minor)

    # Yopildi, and why.
    for manager, actor, day, reason in db.execute(
        select(
            BoardCard.manager_id,
            BoardCardEvent.actor_id,
            _day(BoardCardEvent.created_at),
            BoardCard.close_reason,
        )
        .join(BoardCard, BoardCard.id == BoardCardEvent.card_id)
        .where(
            BoardCard.board == BOARD,
            BoardCardEvent.kind.in_(
                (str(EventKind.CLOSED), str(EventKind.OFFER_ENDED))
            ),
            BoardCardEvent.created_at >= first,
            BoardCardEvent.created_at < after,
            BoardCard.column_code == str(SalesColumn.CLOSED),
        )
    ):
        person = _key(actor or manager)
        cells[(person, day)].closed += 1
        code = reason or str(CloseReason.OTHER)
        reasons[person][code] = reasons[person].get(code, 0) + 1

    # Birinchi aloqa: the minutes from a take to the first call button.
    takes = (
        select(
            BoardCardEvent.card_id,
            BoardCardEvent.actor_id,
            func.min(BoardCardEvent.created_at).label("at"),
        )
        .join(BoardCard, BoardCard.id == BoardCardEvent.card_id)
        .where(
            BoardCard.board == BOARD,
            BoardCardEvent.kind == str(EventKind.TAKEN),
            BoardCardEvent.created_at >= first,
            BoardCardEvent.created_at < after,
        )
        .group_by(BoardCardEvent.card_id, BoardCardEvent.actor_id)
        .subquery()
    )
    touched = aliased(BoardCardEvent)
    for actor, taken_at, touched_at in db.execute(
        select(takes.c.actor_id, takes.c.at, func.min(touched.created_at))
        .join(touched, touched.card_id == takes.c.card_id)
        .where(touched.kind.in_(_CALLED), touched.created_at >= takes.c.at)
        .group_by(takes.c.card_id, takes.c.actor_id, takes.c.at)
    ):
        day = localtime(taken_at).date()
        minutes = max(0.0, (touched_at - taken_at).total_seconds() / 60)
        cells[(_key(actor), day)].first_touch.append(minutes)

    _calls(db, cells, first=first, after=after)

    people = _people(db, {person for person, _ in cells} - {NOBODY})
    team = [
        person
        for person in db.scalars(
            select(User).where(User.is_staff.is_(True), User.is_active.is_(True))
        )
        if works_on(db, person, Board.SALES)
    ]
    for person in team:
        people.setdefault(str(person.id), person)
    allowed = set(people) | {NOBODY} if lead else {str(user.id)}
    if not lead:
        people = {key: p for key, p in people.items() if key in allowed}
        people.setdefault(str(user.id), user)

    total = Figures()
    by_day: dict[date, Figures] = defaultdict(Figures)
    by_person: dict[str, Figures] = defaultdict(Figures)
    for (person, day), cell in cells.items():
        if person not in allowed:
            continue
        total.add(cell)
        by_day[day].add(cell)
        by_person[person].add(cell)

    now = utcnow()
    holding = _holding(db, now=now)
    days = []
    cursor = start
    while cursor <= end:
        figures = by_day.get(cursor, Figures())
        days.append(
            {
                "day": cursor,
                **figures.out(rate_base=figures.leads if lead else figures.taken),
            }
        )
        cursor += timedelta(days=1)

    staff = []
    for key, person in sorted(
        people.items(), key=lambda item: (item[1].full_name or item[1].email).lower()
    ):
        figures = by_person.get(key, Figures())
        open_now, overdue_now = holding.get(key, (0, 0))
        staff.append(
            {
                "staff": {
                    "id": key,
                    "name": person.full_name or person.email,
                    "email": person.email,
                },
                **figures.out(rate_base=figures.taken),
                "open_now": open_now,
                "overdue_now": overdue_now,
                "reasons": _reasons_out(reasons.get(key, {})),
            }
        )
    staff.sort(key=lambda row: (-row["sold"], -row["taken"], row["staff"]["name"]))
    if lead and NOBODY in by_person:
        figures = by_person[NOBODY]
        staff.append(
            {
                "staff": None,
                **figures.out(rate_base=0),
                "open_now": 0,
                "overdue_now": 0,
                "reasons": _reasons_out(reasons.get(NOBODY, {})),
            }
        )

    every_reason: dict[str, int] = {}
    for person, why in reasons.items():
        if person in allowed:
            for code, count in why.items():
                every_reason[code] = every_reason.get(code, 0) + count

    return {
        "date_from": start,
        "date_to": end,
        "scope": "all" if lead else "own",
        "total": total.out(rate_base=total.leads if lead else total.taken),
        "queue": _queue(db, now=now) if lead else None,
        "days": days,
        "staff": staff,
        "reasons": _reasons_out(every_reason),
        "sources": _sources(db, first=first, after=after) if lead else [],
        "campaigns": _campaigns(db, first=first, after=after) if lead else [],
    }


def _calls(
    db: Session,
    cells: dict[tuple[str, date], Figures],
    *,
    first: datetime,
    after: datetime,
) -> None:
    """The office exchange's calls by each staff member, both ways."""
    from app.modules.telephony.models import PhoneCall, PhoneConnection

    for person, day, total, answered, talk in db.execute(
        select(
            PhoneCall.user_id,
            _day(PhoneCall.started_at),
            func.count(),
            func.count().filter(PhoneCall.answered.is_(True)),
            func.coalesce(func.sum(PhoneCall.talk_seconds), 0),
        )
        .join(PhoneConnection, PhoneConnection.id == PhoneCall.connection_id)
        .where(
            PhoneConnection.owner_id.is_(None),
            PhoneCall.user_id.is_not(None),
            PhoneCall.started_at >= first,
            PhoneCall.started_at < after,
        )
        .group_by(PhoneCall.user_id, _day(PhoneCall.started_at))
    ):
        cell = cells[(_key(person), day)]
        cell.calls += int(total)
        cell.calls_answered += int(answered)
        cell.talk_seconds += int(talk)


def _people(db: Session, keys: set[str]) -> dict[str, User]:
    ids = [uuid.UUID(key) for key in keys]
    if not ids:
        return {}
    return {str(p.id): p for p in db.scalars(select(User).where(User.id.in_(ids)))}


def _holding(db: Session, *, now: datetime) -> dict[str, tuple[int, int]]:
    """Per manager now: open cards in hand, and those past their time."""
    return {
        _key(manager): (int(total), int(late))
        for manager, total, late in db.execute(
            select(
                BoardCard.manager_id,
                func.count(),
                func.count().filter(BoardCard.due_at <= now),
            )
            .where(
                BoardCard.board == BOARD,
                BoardCard.closed_at.is_(None),
                BoardCard.manager_id.is_not(None),
            )
            .group_by(BoardCard.manager_id)
        )
    }


def _queue(db: Session, *, now: datetime) -> dict[str, Any]:
    """«Ishlanmagan» now: how many wait and since when the oldest."""
    count, oldest = db.execute(
        select(func.count(), func.min(BoardCard.opened_at)).where(
            BoardCard.board == BOARD,
            BoardCard.column_code == str(SalesColumn.UNWORKED),
            BoardCard.manager_id.is_(None),
        )
    ).one()
    return {"waiting": int(count or 0), "oldest_at": oldest}


def _reasons_out(counts: dict[str, int]) -> list[dict[str, Any]]:
    def label(code: str) -> str:
        if code == OFFER_ENDED_REASON:
            return OFFER_ENDED_LABEL
        if code in CloseReason.values:
            return str(CLOSE_REASON_LABELS[CloseReason(code)])
        return code

    return [
        {"code": code, "label": label(code), "count": count}
        for code, count in sorted(counts.items(), key=lambda item: -item[1])
    ]


def _sources(db: Session, *, first: datetime, after: datetime) -> list[dict[str, Any]]:
    """The period's leads by how they signed up, and how many of them bought
    by now: which door brings buyers."""
    rows: dict[str, list[int]] = {}
    for via, column in db.execute(
        select(User.signup_via, BoardCard.column_code)
        .join(User, User.id == BoardCard.owner_id)
        .where(
            BoardCard.board == BOARD,
            BoardCard.opened_at >= first,
            BoardCard.opened_at < after,
        )
    ):
        code = via or ""
        row = rows.setdefault(code, [0, 0])
        row[0] += 1
        row[1] += 1 if column == SalesColumn.SOLD else 0
    return [
        {
            "code": code,
            "label": str(SIGNUP_VIA_LABELS[SignupVia(code)])
            if code in SignupVia.values
            else "Noma'lum",
            "leads": leads,
            "sold": sold,
            "rate": round(sold * 100 / leads) if leads else 0,
        }
        for code, (leads, sold) in sorted(rows.items(), key=lambda item: -item[1][0])
    ]


CAMPAIGNS_SHOWN = 15


def _campaigns(
    db: Session, *, first: datetime, after: datetime
) -> list[dict[str, Any]]:
    """The period's leads by the landing link's utm_source and utm_campaign,
    and how many of them bought by now. Leads with no marks are left out."""
    source = User.signup_utm["source"].astext
    campaign = User.signup_utm["campaign"].astext
    # One object each, so GROUP BY reads the select's own expression.
    source_text = func.coalesce(source, "")
    campaign_text = func.coalesce(campaign, "")
    rows = db.execute(
        select(
            source_text,
            campaign_text,
            func.count(),
            func.count().filter(BoardCard.column_code == str(SalesColumn.SOLD)),
        )
        .join(User, User.id == BoardCard.owner_id)
        .where(
            BoardCard.board == BOARD,
            BoardCard.opened_at >= first,
            BoardCard.opened_at < after,
            or_(source.is_not(None), campaign.is_not(None)),
        )
        .group_by(source_text, campaign_text)
        .order_by(func.count().desc())
        .limit(CAMPAIGNS_SHOWN)
    )
    return [
        {
            "source": str(src),
            "campaign": str(name),
            "leads": int(leads),
            "sold": int(sold),
            "rate": round(int(sold) * 100 / int(leads)) if leads else 0,
        }
        for src, name, leads, sold in rows
    ]
