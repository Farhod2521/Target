"""A board and a card as the office reads them."""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Select, and_, cast, exists, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH
from sqlalchemy.orm import Session, aliased

from app.common.dates import localtime
from app.modules.accounts.models import User
from app.modules.billing.constants import (
    LIVE_SUBSCRIPTION_STATUSES,
    InvoiceKind,
    InvoiceStatus,
)
from app.modules.billing.models import Invoice, Subscription
from app.modules.boards import reasons
from app.modules.boards.access import Access
from app.modules.boards.constants import (
    ACTION_DUE_OPTIONAL,
    ACTION_DUE_REQUIRED,
    ACTION_NOTE_REQUIRED,
    CARD_ACTION_LABELS,
    CLIENT_SEARCH_ROWS,
    CLOSE_REASON_LABELS,
    CONFIRM_HOURS,
    EVENT_KIND_LABELS,
    OFFER_ENDED_LABEL,
    OFFER_ENDED_REASON,
    RENEWAL_ACTIONS,
    RENEWAL_PLAN_CODES,
    SALES_ACTIONS,
    SEARCH_MAX,
    SUPPORT_ACTION_LABELS,
    SUPPORT_ACTIONS,
    SUPPORT_DONE_COLUMNS,
    TICKET_REASON_LABELS,
    TICKET_TAKE_LIMIT,
    AttemptsFilter,
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
    # Support: a ticket reason's code. Uzaytirish: why the client declined.
    reason: str = ""
    # Uzaytirish: the plan's code, the term's end between two office days,
    # and how many times «Bog'lanib bo'lmadi» was pressed.
    plan: str = ""
    term_from: date | None = None
    term_to: date | None = None
    attempts: str = ""


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
    if filters.reason and board == Board.RENEWAL:
        query = query.where(BoardCard.close_reason == filters.reason)
    elif filters.reason:
        # A ticket about this reason now: it is open on it, or, once the
        # ticket is done, among what it held. Solved long ago does not count.
        open_on = func.jsonb_path_exists(
            BoardCard.reasons,
            cast("$[*] ? (@.code == $code && !exists(@.solved_at))", JSONPATH),
            cast({"code": filters.reason}, JSONB),
        )
        done = and_(
            BoardCard.column_code.in_(SUPPORT_DONE_COLUMNS),
            BoardCard.reasons.contains([{"code": filters.reason}]),
        )
        query = query.where(or_(open_on, done))
    if board == Board.RENEWAL:
        query = _renewal_scoped(query, filters)
    if with_due and filters.due in DueFilter.values:
        query = query.where(_due_clause(filters.due, now))
    words = search.strip()[:SEARCH_MAX]
    if words:
        client = aliased(User)
        like = f"%{words}%"
        # "90 123 45 67" or "(90) 123-45-67" finds +998901234567.
        digits = re.sub(r"[\s()-]", "", words) or words
        found = [
            client.full_name.ilike(like),
            client.email.ilike(like),
            client.phone.ilike(f"%{digits}%"),
        ]
        if board == Board.RENEWAL:
            from app.modules.integrations.models import PageAccount

            # The page's name is how the office knows such a client.
            found.append(
                exists().where(
                    PageAccount.owner_id == BoardCard.owner_id,
                    PageAccount.is_active.is_(True),
                    PageAccount.name.ilike(like),
                )
            )
        query = query.join(client, client.id == BoardCard.owner_id).where(or_(*found))
    return query


def _renewal_scoped(query: Select[Any], filters: Filters) -> Select[Any]:
    from app.modules.boards.renewal import day_bounds

    if filters.plan:
        known = filters.plan in RENEWAL_PLAN_CODES
        query = query.where(
            BoardCard.plan_code == filters.plan if known else BoardCard.id.is_(None)
        )
    if filters.term_from is not None:
        first, _ = day_bounds(filters.term_from, filters.term_from)
        query = query.where(BoardCard.term_ends_at >= first)
    if filters.term_to is not None:
        _, after = day_bounds(filters.term_to, filters.term_to)
        query = query.where(BoardCard.term_ends_at < after)
    if filters.attempts == AttemptsFilter.NONE:
        query = query.where(BoardCard.attempts == 0)
    elif filters.attempts == AttemptsFilter.FEW:
        query = query.where(BoardCard.attempts.between(1, 2))
    elif filters.attempts == AttemptsFilter.MANY:
        query = query.where(BoardCard.attempts >= 3)
    return query


def _order(code: str, board: Board, now: datetime) -> Any:
    if board == Board.RENEWAL:
        from app.modules.boards.renewal import order

        return order(code, now)
    return _order_by_due(code)


def _order_by_due(code: str) -> Any:
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

    # card id -> when its discount started, and from what (boards.offer).
    offered: dict[uuid.UUID, tuple[datetime, str]]
    # owner id -> the bill they opened and may still pay.
    bills: dict[uuid.UUID, Invoice]
    # card id -> what a renewal card shows (boards.renewal).
    renewal: dict[uuid.UUID, dict[str, Any]] = field(default_factory=dict)
    # card id -> what put a ticket in its column, when the client did:
    # ``denied`` (their «Yo'q») or ``client_replied`` (they wrote back).
    marks: dict[uuid.UUID, str] = field(default_factory=dict)


def extras_for(db: Session, cards: list[BoardCard], *, now: datetime) -> Extras:
    """The discounts and open bills of these cards, in three queries."""
    from app.modules.boards.offer import clocks_for
    from app.modules.boards.renewal import briefs

    renewal = briefs(db, cards, now=now)
    # A renewal card shows the client's open bill as a Sales card does.
    billed = [
        card for card in cards if card.board in (str(Board.SALES), str(Board.RENEWAL))
    ]
    sales = [card for card in cards if card.board == str(Board.SALES)]
    marks = _client_marks(db, cards)
    if not billed:
        return Extras(offered={}, bills={}, renewal=renewal, marks=marks)
    bills: dict[uuid.UUID, Invoice] = {}
    for bill in db.scalars(
        open_bills(now)
        .where(Invoice.owner_id.in_([card.owner_id for card in billed]))
        .order_by(Invoice.created_at)
    ):
        if bill.owner_id is not None:
            bills[bill.owner_id] = bill
    offered = clocks_for(db, sales) if sales else {}
    return Extras(offered=offered, bills=bills, renewal=renewal, marks=marks)


_CLIENT_KINDS = (str(EventKind.DENIED), str(EventKind.CLIENT_REPLIED))


def _client_marks(db: Session, cards: list[BoardCard]) -> dict[uuid.UUID, str]:
    """The tickets the client themselves sent back to work: the line that
    moved the card into the column it stands in is theirs. One query."""
    tickets = [
        card
        for card in cards
        if card.board == str(Board.SUPPORT) and card.closed_at is None
    ]
    if not tickets:
        return {}
    return {
        card_id: kind
        for card_id, kind in db.execute(
            select(BoardCardEvent.card_id, BoardCardEvent.kind)
            .join(BoardCard, BoardCard.id == BoardCardEvent.card_id)
            .where(
                BoardCardEvent.card_id.in_([card.id for card in tickets]),
                BoardCardEvent.kind.in_(_CLIENT_KINDS),
                BoardCardEvent.created_at >= BoardCard.column_since,
                BoardCardEvent.to_column == BoardCard.column_code,
            )
        )
    }


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

    clock = extras.offered.get(card.id)
    if clock is None:
        return None
    started, source = clock
    # Sold or closed: the discount is over on the card.
    step = step_at(started, now, source=source) if card.closed_at is None else None
    return {
        "percent": step.percent if step else 0,
        "started_at": started,
        "ends_at": step.ends_at if step else None,
        "source": source,
        "next_percent": step.next_percent if step else 0,
        "next_ends_at": step.next_ends_at if step else None,
    }


def card_brief(card: BoardCard, *, extras: Extras, now: datetime) -> dict[str, Any]:
    owner = card.owner
    # What the ticket is about now, not everything it ever held.
    codes = sorted({str(item.get("code", "")) for item in reasons.shown(card)} - {""})
    mark = extras.marks.get(card.id, "")
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
        "renewal": extras.renewal.get(card.id),
        "client_denied": mark == EventKind.DENIED,
        "client_replied": mark == EventKind.CLIENT_REPLIED,
        "confirm_until": card.column_since + timedelta(hours=CONFIRM_HOURS)
        if card.board == str(Board.SUPPORT)
        and card.column_code == SupportColumn.CONFIRMING
        else None,
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
                base.order_by(*_order(item.code, board, now))
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
    elif card.board == str(Board.RENEWAL):
        offered = RENEWAL_ACTIONS.get(card.column_code, ())
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


def _plan(db: Session, owner: User, *, now: datetime) -> dict[str, Any] | None:
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
        "expired": live.expires_at <= now,
        "setup_done": live.setup_completed_at is not None,
    }


def _reason_out(item: dict[str, Any]) -> dict[str, Any]:
    target = item.get("target") if isinstance(item.get("target"), dict) else None
    return {
        "code": str(item.get("code", "")),
        "label": _reason_label(str(item.get("code", ""))),
        "detail": str(item.get("detail", "")),
        "at": item.get("at"),
        "state": "open" if reasons.is_open(item) else "solved",
        "solved_at": item.get("solved_at"),
        "solved_by": str(item.get("solved_by", "")),
        "solved_note": str(item.get("solved_note", "")),
        "denied_at": item.get("denied_at"),
        "raw": str(item.get("raw", "")),
        "target": {
            "kind": str(target.get("kind", "")),
            "id": str(target.get("id", "")),
            "name": str(target.get("name", "")),
        }
        if target
        else None,
    }


# Where the client's answer stands, by the column a solved ticket is in.
_ANSWERS = {
    str(SupportColumn.CONFIRMING): "waiting",
    str(SupportColumn.RESOLVED): "yes",
    str(SupportColumn.CLOSED): "silent",
}


def _resolution(card: BoardCard) -> dict[str, Any] | None:
    """A ticket called solved: how, by whom, and what the client said."""
    if card.board != str(Board.SUPPORT) or card.column_code not in _ANSWERS:
        return None
    solved = reasons.last_round(card)
    if not solved or reasons.open_reasons(card):
        return None
    first = solved[0]
    return {
        "note": str(first.get("solved_note", "")),
        "by": str(first.get("solved_by", "")),
        "at": first.get("solved_at"),
        "client": _ANSWERS[card.column_code],
        "count": len(solved),
    }


def _troubles(db: Session, card: BoardCard, *, now: datetime) -> list[dict[str, Any]]:
    """What is wrong with the client's account right now, as the office's
    own list names it: Support reads the state, not only the ticket."""
    if card.board != str(Board.SUPPORT):
        return []
    from app.modules.backoffice.selectors.problems import problems_of

    return [
        {
            "kind": problem.kind,
            "label": problem.label,
            "what": problem.what,
            "urgent": problem.urgent,
            "since": problem.since,
        }
        for problem in problems_of(db, owner_id=card.owner_id, now=now)
    ]


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
    from app.modules.boards.renewal import decline_label

    reason = (
        decline_label(card.close_reason)
        if card.board == str(Board.RENEWAL)
        else str(CLOSE_REASON_LABELS[CloseReason(card.close_reason)])
        if card.close_reason in CloseReason.values
        else OFFER_ENDED_LABEL
        if card.close_reason == OFFER_ENDED_REASON
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
            "plan": _plan(db, owner, now=now),
            "troubles": _troubles(db, card, now=now),
        },
        "ticket_reasons": [_reason_out(item) for item in reversed(card.reasons or [])],
        "resolution": _resolution(card),
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
