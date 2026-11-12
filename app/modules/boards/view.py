"""A board and a card as the office reads them."""

import re
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.modules.accounts.models import User
from app.modules.billing.constants import LIVE_SUBSCRIPTION_STATUSES
from app.modules.billing.models import Subscription
from app.modules.boards.access import Access
from app.modules.boards.constants import (
    CARD_ACTION_LABELS,
    CLOSE_REASON_LABELS,
    EVENT_KIND_LABELS,
    SALES_ACTIONS,
    SEARCH_MAX,
    SUPPORT_ACTIONS,
    TICKET_REASON_LABELS,
    Board,
    CloseReason,
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


def _scoped(
    query: Select[Any], *, board: Board, user: User, access: Access, search: str
) -> Select[Any]:
    query = query.where(BoardCard.board == str(board))
    if board == Board.SALES and not access.leads_board(board):
        query = query.where(BoardCard.manager_id == user.id)
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
    # A queue is worked oldest first; elsewhere the latest move is on top.
    if code == SalesColumn.UNWORKED:
        return (BoardCard.opened_at, BoardCard.id)
    if code == SupportColumn.NEW:
        return (BoardCard.column_since, BoardCard.id)
    return (BoardCard.column_since.desc(), BoardCard.id)


def _reason_label(code: str) -> str:
    if code in TicketReason.values:
        return str(TICKET_REASON_LABELS[TicketReason(code)])
    return code


def card_brief(card: BoardCard) -> dict[str, Any]:
    owner = card.owner
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
        "needs_support": card.needs_support,
        "reasons": sorted(
            {str(item.get("code", "")) for item in card.reasons or []} - {""}
        ),
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
    column: str = "",
    search: str = "",
    offset: int = 0,
    limit: int,
) -> dict[str, Any]:
    """Every column this person sees with its count and first cards; with
    ``column``, that one column from ``offset`` on."""
    shown: list[ColumnView] = columns_for(db, board=board, access=access)
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
        )
        total = int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)
        cards = list(
            db.scalars(
                base.order_by(*_order(item.code))
                .offset(offset if column else 0)
                .limit(limit)
            )
        )
        out.append(
            {
                "code": item.code,
                "name": item.name,
                "position": item.position,
                "kind": item.kind,
                "is_final": item.is_final,
                "total": total,
                "cards": [card_brief(card) for card in cards],
            }
        )
    return {"board": str(board), "columns": out}


def _actions(card: BoardCard) -> list[dict[str, str]]:
    if card.board == str(Board.SUPPORT):
        offered = SUPPORT_ACTIONS.get(card.column_code, ())
    elif card.closed_at is not None:
        offered = ()
    else:
        offered = SALES_ACTIONS.get(card.column_code, ())
    return [
        {"value": str(action), "label": str(CARD_ACTION_LABELS[action])}
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


def _offer(db: Session, *, card: BoardCard, now: datetime) -> dict[str, Any] | None:
    from app.modules.boards.offer import offered_at, step_at

    if card.board != str(Board.SALES):
        return None
    started = offered_at(db, card_id=card.id)
    if started is None:
        return None
    # Sold or closed: the offer no longer applies, as the bill sees it.
    step = step_at(started, now) if card.closed_at is None else None
    return {
        "percent": step.percent if step else 0,
        "started_at": started,
        "ends_at": step.ends_at if step else None,
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
    return {
        **card_brief(card),
        "client": {
            **card_brief(card)["client"],
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
        "offer": _offer(db, card=card, now=now),
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
