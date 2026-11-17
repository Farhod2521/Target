"""Who answers a client in the one chat: the assistant, or one person.

The client has one chat - the assistant's, with Support in it. A person in
Support takes it with «Men javob beraman»; from then on the assistant does
not answer this client, and what the person writes lands in the client's
open thread. One person at a time: it is the client's Support ticket's
person (``BoardCard.manager_id``) while ``BoardCard.chat_taken_at`` is set,
so the chat and the ticket never belong to two people.

Who may take it
    The ticket's own person, or anybody in Support when nobody has the
    ticket (it becomes theirs, within «Zayavka olish»'s limit). The Owner
    and the superuser take any chat, and give it - with the ticket - to
    somebody in Support. A client with no open ticket has one opened.

When the assistant answers again
    «AI ga qaytarish», pressed by the person or the Owner; or the ticket is
    solved, closed or left with nobody (``services.move`` clears the mark).

The caller commits.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.boards.access import access_for, works_on
from app.modules.boards.constants import (
    SUPPORT_DONE_COLUMNS,
    Board,
    EventKind,
    SupportColumn,
    TicketReason,
)
from app.modules.boards.exceptions import (
    ChatHeld,
    ChatNotTaken,
    NotOnBoard,
    TicketOfAnother,
)
from app.modules.boards.models import BoardCard

# The line on a ticket opened only so that somebody could answer in the chat.
OPENED_FOR_CHAT: Final = "Chatda javob berish uchun ochildi"


@dataclass(frozen=True, slots=True)
class Hold:
    holder: User
    since: datetime
    card_id: UUID


def _name(user: User) -> str:
    return user.full_name or user.email


def _card(db: Session, owner_id: UUID, *, lock: bool = False) -> BoardCard | None:
    query = select(BoardCard).where(
        BoardCard.board == str(Board.SUPPORT),
        BoardCard.owner_id == owner_id,
        BoardCard.term_ends_at.is_(None),
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def _hold_on(db: Session, card: BoardCard | None) -> Hold | None:
    if (
        card is None
        or card.chat_taken_at is None
        or card.manager_id is None
        or card.column_code in SUPPORT_DONE_COLUMNS
    ):
        return None
    holder = db.get(User, card.manager_id)
    if holder is None:
        return None
    return Hold(holder=holder, since=card.chat_taken_at, card_id=card.id)


def hold_of(db: Session, *, owner_id: UUID) -> Hold | None:
    """Who answers this client now; nobody means the assistant does."""
    return _hold_on(db, _card(db, owner_id))


def _open_card(db: Session, *, client: User, user: User, now: datetime) -> BoardCard:
    """The client's ticket, locked; opened or reopened when it is not open."""
    from app.modules.boards.tickets import raise_ticket

    card = _card(db, client.id, lock=True)
    if card is None or card.column_code in SUPPORT_DONE_COLUMNS:
        raise_ticket(
            db,
            owner_id=client.id,
            reason=TicketReason.MANUAL,
            ref=f"chat:{user.id}:{now.isoformat()}",
            now=now,
            detail=OPENED_FOR_CHAT,
            actor=user,
        )
        card = _card(db, client.id, lock=True)
    assert card is not None
    return card


def _give(
    db: Session,
    *,
    card: BoardCard,
    to: User,
    actor: User,
    kind: EventKind,
    now: datetime,
) -> None:
    """The ticket and the chat are ``to``'s from now."""
    from app.modules.boards.services import move, record

    if card.manager_id != to.id:
        card.manager_id = to.id
        card.due_at = None
    card.chat_taken_at = now
    if card.column_code == SupportColumn.NEW:
        move(
            db,
            card=card,
            to=str(SupportColumn.IN_PROGRESS),
            kind=kind,
            now=now,
            actor=actor,
            body=_name(to),
        )
    else:
        record(db, card=card, kind=kind, now=now, actor=actor, body=_name(to))
    _point_thread(db, owner_id=card.owner_id, now=now)


def _point_thread(db: Session, *, owner_id: UUID, now: datetime) -> None:
    """The person's words go to the thread the client is in."""
    from app.modules.assistant.services.support import point_at_open_thread

    point_at_open_thread(db, owner_id=owner_id, now=now)


def take_chat(db: Session, *, client: User, user: User, now: datetime) -> Hold:
    """«Men javob beraman». Pressing it again changes nothing."""
    from app.modules.boards.services import _room_to_take

    full = access_for(db, user).full
    card = _open_card(db, client=client, user=user, now=now)
    held = _hold_on(db, card)
    if held is not None and held.holder.id == user.id:
        return held
    if not full:
        if held is not None:
            raise ChatHeld(_name(held.holder))
        if card.manager_id not in (None, user.id):
            other = db.get(User, card.manager_id)
            raise TicketOfAnother(_name(other) if other else "boshqa xodim")
        if card.manager_id is None:
            _room_to_take(db, user=user)
    _give(db, card=card, to=user, actor=user, kind=EventKind.CHAT_TAKEN, now=now)
    found = _hold_on(db, card)
    assert found is not None
    return found


def hand_chat(
    db: Session, *, client: User, user: User, to_id: UUID, now: datetime
) -> Hold:
    """The Owner gives the chat, with the ticket, to somebody in Support."""
    from app.modules.boards.exceptions import CardNotFound

    if not access_for(db, user).full:
        raise CardNotFound
    target = db.get(User, to_id)
    if target is None or not works_on(db, target, Board.SUPPORT):
        raise NotOnBoard
    card = _open_card(db, client=client, user=user, now=now)
    held = _hold_on(db, card)
    if held is not None and held.holder.id == target.id:
        return held
    _give(db, card=card, to=target, actor=user, kind=EventKind.CHAT_HANDED, now=now)
    found = _hold_on(db, card)
    assert found is not None
    return found


def release_chat(db: Session, *, client: User, user: User, now: datetime) -> None:
    """«AI ga qaytarish»: the person who has it, or the Owner. The ticket
    stays the person's; only the chat goes back to the assistant."""
    from app.modules.boards.services import record

    card = _card(db, client.id, lock=True)
    held = _hold_on(db, card)
    if card is None or held is None:
        if card is not None:
            card.chat_taken_at = None
        return
    if held.holder.id != user.id and not access_for(db, user).full:
        raise ChatHeld(_name(held.holder))
    card.chat_taken_at = None
    record(db, card=card, kind=EventKind.CHAT_RELEASED, now=now, actor=user)


@dataclass(frozen=True, slots=True)
class Seen:
    """The chat's hold as one viewer in the office sees it."""

    hold: Hold | None
    mine: bool
    can_take: bool
    can_release: bool
    can_hand: bool
    # Who works with this client, when that is why it cannot be taken.
    busy_with: str


def seen_by(db: Session, *, client: User, user: User) -> Seen:
    """What ``take_chat``, ``release_chat`` and ``hand_chat`` would allow."""
    full = access_for(db, user).full
    card = _card(db, client.id)
    held = _hold_on(db, card)
    mine = held is not None and held.holder.id == user.id
    busy = ""
    if held is not None and not mine:
        busy = _name(held.holder)
    elif held is None and card is not None and card.manager_id not in (None, user.id):
        other = db.get(User, card.manager_id)
        busy = _name(other) if other is not None else ""
    return Seen(
        hold=held,
        mine=mine,
        can_take=not mine and (full or not busy),
        can_release=held is not None and (mine or full),
        can_hand=full,
        busy_with="" if full else busy,
    )


def check_writer(
    db: Session, *, owner_id: UUID, sender: User, now: datetime, take: bool = False
) -> None:
    """Somebody in Support writes to this client: only the person who has
    the chat. ``take``: a reply from Telegram, where there is no button -
    it takes a free chat the way the button would."""
    held = hold_of(db, owner_id=owner_id)
    if held is not None and held.holder.id == sender.id:
        return
    if held is not None:
        raise ChatHeld(_name(held.holder))
    if not take:
        raise ChatNotTaken
    client = db.get(User, owner_id)
    if client is None:
        raise ChatNotTaken
    take_chat(db, client=client, user=sender, now=now)


__all__ = [
    "OPENED_FOR_CHAT",
    "Hold",
    "Seen",
    "check_writer",
    "hand_chat",
    "hold_of",
    "release_chat",
    "seen_by",
    "take_chat",
]
