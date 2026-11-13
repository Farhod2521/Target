"""A board and a card as the office reads them."""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.common.dates import localtime
from app.modules.accounts.models import User
from app.modules.billing.constants import (
    LIVE_SUBSCRIPTION_STATUSES,
    InvoiceKind,
    InvoiceStatus,
)
from app.modules.billing.models import Invoice, Subscription
from app.modules.boards.access import Access
from app.modules.boards.constants import (
    ACTION_DUE_OPTIONAL,
    ACTION_DUE_REQUIRED,
    ACTION_NOTE_REQUIRED,
    CARD_ACTION_LABELS,
    CLIENT_SEARCH_ROWS,
    CLOSE_REASON_LABELS,
    EVENT_KIND_LABELS,
    SALES_ACTIONS,
    SEARCH_MAX,
    SUPPORT_ACTION_LABELS,
    SUPPORT_ACTIONS,
    TICKET_REASON_LABELS,
    TICKET_TAKE_LIMIT,
    Board,
    CloseReason,
    DueFilter,
    EventKind,
    SalesColumn,
    SupportColumn,
    TicketReason,
)
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.selectors import ColumnView, columns_for


def _person(user: User | None) -> dict[str, str] | None:
    if user is None:
        return None
    return {
        "id": str(user.id),
        "name": user.full_name or user.email,
        "email": user.email,
    }


@dataclass(frozen=True, slots=True)
class Filters:
    """What narrows a board besides the search."""

    mine: bool = False
    # A staff member's id, or ``none`` for cards nobody works.
    manager: str = ""
    due: str = ""
    # Support: a ticket reason's code.
    reason: str = ""


def today_bounds(now: datetime) -> tuple[datetime, datetime]:
    """The office's day that ``now`` is in."""
    start = datetime.combine(localtime(now).date(), time.min, localtime(now).tzinfo)
    return start, start + timedelta(days=1)


def _due_clause(due: str, now: datetime) -> Any:
    if due == DueFilter.OVERDUE:
        return BoardCard.due_at <= now
    if due == DueFilter.TODAY:
        start, end = today_bounds(now)
        return and_(BoardCard.due_at >= start, BoardCard.due_at < end)
    return BoardCard.due_at.is_not(None)


def _scoped(
    query: Select[Any],
    *,
    board: Board,
    user: User,
    access: Access,
    search: str,
    filters: Filters,
    now: datetime,
    with_due: bool = True,
) -> Select[Any]:
    query = query.where(BoardCard.board == str(board))
    # Only a board's lead reads other people's cards.
    if not access.leads_board(board):
        query = query.where(BoardCard.manager_id == user.id)
    if filters.mine:
        query = query.where(BoardCard.manager_id == user.id)
    if filters.manager == "none":
        query = query.where(BoardCard.manager_id.is_(None))
    elif filters.manager:
        try:
            query = query.where(BoardCard.manager_id == uuid.UUID(filters.manager))
        except ValueError:
            query = query.where(BoardCard.id.is_(None))
    if filters.reason:
        query = query.where(BoardCard.reasons.contains([{"code": filters.reason}]))
    if with_due and filters.due in DueFilter.values:
        query = query.where(_due_clause(filters.due, now))
    words = search.strip()[:SEARCH_MAX]
    if words:
        client = aliased(User)
        like = f"%{words}%"
        # "90 123 45 67" or "(90) 123-45-67" finds +998901234567.
        digits = re.sub(r"[\s()-]", "", words) or words
        query = query.join(client, client.id == BoardCard.owner_id).where(
            or_(
                client.full_name.ilike(like),
                client.email.ilike(like),
                client.phone.ilike(f"%{digits}%"),
            )
        )
    return query


def _order(code: str) -> Any:
    # The nearest deadline is on top, so an overdue card is the first seen.
    # Then: the lead queue newest first, as «Lid olish» gives it; Support's
    # queue oldest first; elsewhere the latest move.
    due = BoardCard.due_at.asc().nulls_last()
    if code == SalesColumn.UNWORKED:
        return (due, BoardCard.opened_at.desc(), BoardCard.id)
    if code == SupportColumn.NEW:
        return (due, BoardCard.column_since, BoardCard.id)
    return (due, BoardCard.column_since.desc(), BoardCard.id)


def _reason_label(code: str) -> str:
    if code in TicketReason.values:
        return str(TICKET_REASON_LABELS[TicketReason(code)])
    return code


@dataclass(frozen=True, slots=True)
class Extras:
    """What a Sales card shows from outside its own row."""

    # card id -> when «Chegirma berish» was pressed.
    offered: dict[uuid.UUID, datetime]
    # owner id -> the bill they opened and may still pay.
    bills: dict[uuid.UUID, Invoice]


def extras_for(db: Session, cards: list[BoardCard], *, now: datetime) -> Extras:
    """The offers and open bills of these cards, in two queries."""
    from app.modules.boards.offer import OFFERED_REF

    sales = [card for card in cards if card.board == str(Board.SALES)]
    if not sales:
        return Extras(offered={}, bills={})
    offered = {
        card_id: at
        for card_id, at in db.execute(
            select(BoardCardEvent.card_id, BoardCardEvent.created_at).where(
                BoardCardEvent.card_id.in_([card.id for card in sales]),
                BoardCardEvent.ref == OFFERED_REF,
            )
        )
    }
    bills: dict[uuid.UUID, Invoice] = {}
    for bill in db.scalars(
        open_bills(now)
        .where(Invoice.owner_id.in_([card.owner_id for card in sales]))
        .order_by(Invoice.created_at)
    ):
        if bill.owner_id is not None:
            bills[bill.owner_id] = bill
    return Extras(offered=offered, bills=bills)


def open_bills(at: datetime) -> Select[Any]:
    """Plan bills a client opened and may still pay at ``at``."""
    return select(Invoice).where(
        Invoice.kind == str(InvoiceKind.PLAN),
        or_(
            and_(Invoice.status == str(InvoiceStatus.PENDING), Invoice.expires_at > at),
            Invoice.status == str(InvoiceStatus.HELD),
        ),
    )


def _brief_offer(
    card: BoardCard, extras: Extras, now: datetime
) -> dict[str, Any] | None:
    from app.modules.boards.offer import step_at

    started = extras.offered.get(card.id)
    if started is None:
        return None
    # Sold or closed: the offer no longer applies, as the bill sees it.
    step = step_at(started, now) if card.closed_at is None else None
    return {
        "percent": step.percent if step else 0,
        "started_at": started,
        "ends_at": step.ends_at if step else None,
    }


def card_brief(card: BoardCard, *, extras: Extras, now: datetime) -> dict[str, Any]:
    owner = card.owner
    codes = sorted({str(item.get("code", "")) for item in card.reasons or []} - {""})
    return {
        "id": str(card.id),
        "board": card.board,
        "column": card.column_code,
        "client": {
            "id": str(owner.id),
            "name": owner.full_name or owner.email,
            "email": owner.email,
            "phone": owner.phone,
            "signed_up_at": owner.date_joined,
        },
        "manager": _person(card.manager),
        "contact_mark": card.contact_mark,
        "attempts": card.attempts,
        "needs_support": card.needs_support,
        "reasons": codes,
        "reason_chips": [
            {"code": code, "label": _reason_label(code)} for code in codes
        ],
        "due_at": card.due_at,
        "overdue": card.due_at is not None and card.due_at <= now,
        "offer": _brief_offer(card, extras, now),
        "has_bill": card.closed_at is None and card.owner_id in extras.bills,
        "opened_at": card.opened_at,
        "column_since": card.column_since,
        "closed_at": card.closed_at,
    }


def board_view(
    db: Session,
    *,
    board: Board,
    user: User,
    access: Access,
    now: datetime,
    column: str = "",
    search: str = "",
    filters: Filters = Filters(),
    offset: int = 0,
    limit: int,
) -> dict[str, Any]:
    """Every column this person sees with its count and first cards; with
    ``column``, that one column from ``offset`` on. ``due`` counts the
    deadlines under the same search and filters, whatever the due filter."""
    shown: list[ColumnView] = columns_for(db, board=board, access=access)
    codes = [item.code for item in shown]
    if column:
        shown = [item for item in shown if item.code == column]
    out = []
    for item in shown:
        base = _scoped(
            select(BoardCard).where(BoardCard.column_code == item.code),
            board=board,
            user=user,
            access=access,
            search=search,
            filters=filters,
            now=now,
        )
        total = int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)
        cards = list(
            db.scalars(
                base.order_by(*_order(item.code))
                .offset(offset if column else 0)
                .limit(limit)
            )
        )
        extras = extras_for(db, cards, now=now)
        out.append(
            {
                "code": item.code,
                "name": item.name,
                "position": item.position,
                "kind": item.kind,
                "is_final": item.is_final,
                "total": total,
                "cards": [card_brief(card, extras=extras, now=now) for card in cards],
            }
        )

    def counted(due: DueFilter) -> int:
        query = _scoped(
            select(BoardCard).where(
                BoardCard.column_code.in_(codes), _due_clause(due, now)
            ),
            board=board,
            user=user,
            access=access,
            search=search,
            filters=filters,
            now=now,
            with_due=False,
        )
        return int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)

    return {
        "board": str(board),
        "take": _take(db, user=user) if board == Board.SUPPORT else None,
        "due": {
            "overdue": counted(DueFilter.OVERDUE),
            "today": counted(DueFilter.TODAY),
        },
        "columns": out,
    }


def _take(db: Session, *, user: User) -> dict[str, int]:
    """What «Zayavka olish» shows: how many tickets wait for somebody, how
    many this person has in Ishlanmoqda, and the most they may."""
    from app.modules.boards.services import working_count

    queue = db.scalar(
        select(func.count())
        .select_from(BoardCard)
        .where(
            BoardCard.board == str(Board.SUPPORT),
            BoardCard.column_code == str(SupportColumn.NEW),
            BoardCard.manager_id.is_(None),
        )
    )
    return {
        "queue": int(queue or 0),
        "working": working_count(db, user_id=user.id),
        "limit": TICKET_TAKE_LIMIT,
    }


def _actions(card: BoardCard) -> list[dict[str, Any]]:
    if card.board == str(Board.SUPPORT):
        offered = SUPPORT_ACTIONS.get(card.column_code, ())
    elif card.closed_at is not None:
        offered = ()
    else:
        offered = SALES_ACTIONS.get(card.column_code, ())
    labels = SUPPORT_ACTION_LABELS if card.board == str(Board.SUPPORT) else {}
    return [
        {
            "value": str(action),
            "label": str(labels.get(action, CARD_ACTION_LABELS[action])),
            "due": "required"
            if action in ACTION_DUE_REQUIRED
            else "optional"
            if action in ACTION_DUE_OPTIONAL
            else "",
            "note_required": action in ACTION_NOTE_REQUIRED,
        }
        for action in offered
    ]


def _support_chat(db: Session, owner: User) -> str | None:
    from app.modules.supportchat.models import SupportConversation

    found = db.scalar(
        select(SupportConversation.id).where(SupportConversation.owner_id == owner.id)
    )
    return str(found) if found else None


def _plan(db: Session, owner: User) -> dict[str, Any] | None:
    live = db.scalar(
        select(Subscription)
        .where(
            Subscription.owner_id == owner.id,
            Subscription.status.in_([str(s) for s in LIVE_SUBSCRIPTION_STATUSES]),
        )
        .order_by(Subscription.expires_at.desc())
        .limit(1)
    )
    if live is None:
        return None
    return {
        "name": live.plan.name,
        "status": live.status,
        "expires_at": live.expires_at,
        "setup_done": live.setup_completed_at is not None,
    }


def _bill(extras: Extras, card: BoardCard) -> dict[str, Any] | None:
    bill = extras.bills.get(card.owner_id)
    if bill is None or card.closed_at is not None:
        return None
    return {
        "number": bill.number,
        "plan": bill.plan.name if bill.plan else "",
        "amount_minor": bill.amount_minor,
        "currency": bill.currency,
        "status": bill.status,
        "expires_at": bill.expires_at,
    }


def card_detail(db: Session, *, card: BoardCard, now: datetime) -> dict[str, Any]:
    owner = card.owner
    events = list(
        db.scalars(
            select(BoardCardEvent)
            .where(BoardCardEvent.card_id == card.id)
            .order_by(BoardCardEvent.created_at.desc(), BoardCardEvent.id)
        )
    )
    actors = {
        person.id: person
        for person in db.scalars(
            select(User).where(User.id.in_({e.actor_id for e in events if e.actor_id}))
        )
    }
    reason = (
        str(CLOSE_REASON_LABELS[CloseReason(card.close_reason)])
        if card.close_reason in CloseReason.values
        else ""
    )
    extras = extras_for(db, [card], now=now)
    brief = card_brief(card, extras=extras, now=now)
    # Imported here: telephony's routes read who is on a board.
    from app.modules.telephony import calls as phone_calls

    return {
        **brief,
        "calls": phone_calls.for_client(db, owner=owner),
        "client": {
            **brief["client"],
            "role": owner.role,
            "language": owner.language,
            "last_login": owner.last_login,
            "plan": _plan(db, owner),
        },
        "ticket_reasons": [
            {
                "code": str(item.get("code", "")),
                "label": _reason_label(str(item.get("code", ""))),
                "detail": str(item.get("detail", "")),
                "at": item.get("at"),
            }
            for item in reversed(card.reasons or [])
        ],
        "bill": _bill(extras, card),
        "support_chat_id": _support_chat(db, owner),
        "close_reason": card.close_reason,
        "close_reason_label": reason,
        "close_note": card.close_note,
        "actions": _actions(card),
        "history": [
            {
                "kind": event.kind,
                "label": str(EVENT_KIND_LABELS.get(EventKind(event.kind), event.kind))
                if event.kind in EventKind.values
                else event.kind,
                "from_column": event.from_column,
                "to_column": event.to_column,
                "actor": _person(actors.get(event.actor_id))
                if event.actor_id
                else None,
                "body": event.body,
                "at": event.created_at,
            }
            for event in events
        ],
    }


def board_staff(db: Session, *, board: Board) -> list[dict[str, str]]:
    """Who can be given a card on this board: active staff with its role."""
    from app.modules.boards.access import works_on

    people = db.scalars(
        select(User)
        .where(User.is_staff.is_(True), User.is_active.is_(True))
        .order_by(User.full_name, User.email)
    )
    return [
        {"id": str(p.id), "name": p.full_name or p.email, "email": p.email}
        for p in people
        if works_on(db, p, board)
    ]


def search_clients(db: Session, *, board: Board, q: str) -> list[dict[str, Any]]:
    """Signed-up clients a card may be opened for, by email, phone or name,
    each with the card they already have on this board."""
    words = q.strip()[:SEARCH_MAX]
    if len(words) < 3:
        return []
    like = f"%{words}%"
    digits = re.sub(r"[\s()-]", "", words) or words
    people = list(
        db.scalars(
            select(User)
            .where(
                User.is_staff.is_(False),
                User.is_superuser.is_(False),
                User.is_active.is_(True),
                User.crm_owner_id.is_(None),
                or_(
                    User.email.ilike(like),
                    User.phone.ilike(f"%{digits}%"),
                    User.full_name.ilike(like),
                ),
            )
            .order_by(User.date_joined.desc())
            .limit(CLIENT_SEARCH_ROWS)
        )
    )
    cards = {
        card.owner_id: card
        for card in db.scalars(
            select(BoardCard).where(
                BoardCard.board == str(board),
                BoardCard.owner_id.in_([person.id for person in people]),
            )
        )
    }
    return [
        {
            "id": str(person.id),
            "name": person.full_name or person.email,
            "email": person.email,
            "phone": person.phone,
            "signed_up_at": person.date_joined,
            "card": {
                "id": str(cards[person.id].id),
                "column": cards[person.id].column_code,
                "closed": cards[person.id].closed_at is not None,
            }
            if person.id in cards
            else None,
        }
        for person in people
    ]
