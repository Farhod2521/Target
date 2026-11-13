"""What can be pressed under an answer, and where each press has got to.

Three kinds, one door. A **ticket** goes to Support: the request is written
into the client's support chat (Telegram follows from its hook) and put on
Support's board. A **change** is the old chat's prepared change, carried out
by the Reklama screen's own service. An **offer** is a proposal the agent had
already made, approved by the Amallar screen's own service.

Nothing is carried out anywhere else: the model only ever prepares a button.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.exceptions import DomainError
from app.common.throttle import hit
from app.modules.accounts.models import User
from app.modules.assistant.constants import (
    TICKET_ANSWER_CHARS,
    TICKET_BUCKET,
    TICKETS_PER_DAY,
    Author,
    ButtonKind,
    ButtonState,
)
from app.modules.assistant.models import AssistantMessage, AssistantSession
from app.modules.assistant.selectors.threads import message_for
from app.modules.supportchat.constants import MAX_BODY_CHARS, MessageSource

logger = logging.getLogger(__name__)

TICKET_HEADER = "🤖 AI chatdan zayavka"
SENT_WORDS = "Mutaxassisga yuborildi. Javob shu chatga keladi."
WORKING_TICKET = "Mutaxassis ishlayapti."
RESOLVED_WORDS = "Hal qilindi."
WORKING = "Bajarilmoqda."
APPLIED = "Bajarildi."
GONE_WORDS = "Bu tugma endi mavjud emas."
DISMISSED_WORDS = "Bekor qilindi."
TOO_MANY = "Bugun juda ko'p zayavka yuborildi. Ertaga yana yuborishingiz mumkin."
NOT_SENT = "Zayavka yuborilmadi. Birozdan so'ng qayta urining."


@dataclass(frozen=True, slots=True)
class Pressed:
    """One button as the page draws it after a press, or when it asks."""

    kind: str
    key: str
    state: str
    text: str


class TooManyTickets(DomainError):
    status_code = 429

    def __init__(self) -> None:
        super().__init__(TOO_MANY)


def press(
    db: Session, *, owner: User, message_id: str, key: str, now: datetime
) -> Pressed:
    """The client pressed a button. The caller commits."""
    row, index = _found(db, owner=owner, message_id=message_id, key=key, lock=True)
    if row is None or index < 0:
        return Pressed(kind="", key=key, state=ButtonState.GONE, text=GONE_WORDS)
    item = row.buttons[index]
    kind = str(item.get("kind", ""))
    if item.get("state") != ButtonState.OPEN:
        return state_of(db, owner=owner, message_id=message_id, key=key, now=now)
    if kind == ButtonKind.TICKET:
        return _send_ticket(db, owner=owner, row=row, index=index, now=now)
    if kind == ButtonKind.CHANGE:
        return _confirm_change(db, owner=owner, row=row, index=index)
    if kind == ButtonKind.OFFER:
        return _approve_offer(db, owner=owner, row=row, index=index)
    return Pressed(kind=kind, key=key, state=ButtonState.GONE, text=GONE_WORDS)


def dismiss(
    db: Session, *, owner: User, message_id: str, key: str, now: datetime
) -> Pressed:
    """The client said no: the button goes and nothing was ever sent."""
    row, index = _found(db, owner=owner, message_id=message_id, key=key, lock=True)
    if row is None or index < 0:
        return Pressed(kind="", key=key, state=ButtonState.GONE, text=GONE_WORDS)
    item = row.buttons[index]
    if item.get("state") != ButtonState.OPEN:
        return state_of(db, owner=owner, message_id=message_id, key=key, now=now)
    _write(db, row, index, state=ButtonState.DISMISSED)
    return Pressed(
        kind=str(item.get("kind", "")),
        key=key,
        state=ButtonState.DISMISSED,
        text=DISMISSED_WORDS,
    )


def state_of(
    db: Session, *, owner: User, message_id: str, key: str, now: datetime
) -> Pressed:
    """Where a button has got to. Asked until it stops moving."""
    row, index = _found(db, owner=owner, message_id=message_id, key=key)
    if row is None or index < 0:
        return Pressed(kind="", key=key, state=ButtonState.GONE, text=GONE_WORDS)
    return drawn(db, owner=owner, item=row.buttons[index], now=now)


def drawn(db: Session, *, owner: User, item: dict[str, Any], now: datetime) -> Pressed:
    """One stored button with its state as it is right now."""
    kind, key = str(item.get("kind", "")), str(item.get("key", ""))
    state = str(item.get("state", ButtonState.OPEN))
    if state == ButtonState.OPEN:
        return Pressed(kind=kind, key=key, state=state, text="")
    if state == ButtonState.DISMISSED:
        return Pressed(kind=kind, key=key, state=state, text=DISMISSED_WORDS)
    if kind == ButtonKind.TICKET:
        return _ticket_state(db, owner=owner, key=key)
    if kind == ButtonKind.CHANGE:
        return _change_state(db, owner=owner, item=item)
    if kind == ButtonKind.OFFER:
        return _offer_state(db, owner=owner, item=item, now=now)
    return Pressed(kind=kind, key=key, state=state, text="")


def buttons_of(
    db: Session, *, owner: User, row: Any, now: datetime
) -> list[dict[str, Any]]:
    """A row's buttons for the screen: what was stored, with ``state`` and
    ``state_text`` as they are now."""
    shown: list[dict[str, Any]] = []
    for item in row.buttons or ():
        if not isinstance(item, dict):
            continue
        now_is = drawn(db, owner=owner, item=item, now=now)
        shown.append({**item, "state": now_is.state, "state_text": now_is.text})
    return shown


def ticket_text(*, question: str, summary: str, checked: list[str], answer: str) -> str:
    """What Support reads: the problem, what was checked, what was said."""
    parts = [TICKET_HEADER, ""]
    if summary:
        parts += [summary, ""]
    if question:
        parts += [f"Mijoz savoli: {question}", ""]
    if checked:
        parts += ["AI tekshirdi:", *(f"• {line}" for line in checked), ""]
    said = " ".join(answer.split())
    if said:
        if len(said) > TICKET_ANSWER_CHARS:
            said = said[: TICKET_ANSWER_CHARS - 1].rstrip() + "…"
        parts.append(f"AI javobi: {said}")
    return "\n".join(parts).strip()[:MAX_BODY_CHARS]


def _found(
    db: Session, *, owner: User, message_id: str, key: str, lock: bool = False
) -> tuple[AssistantMessage | None, int]:
    row = message_for(db, owner=owner, pk=message_id, lock=lock)
    if row is None or row.author != Author.AI:
        return None, -1
    for index, item in enumerate(row.buttons or ()):
        if isinstance(item, dict) and item.get("key") == key:
            return row, index
    return row, -1


def _write(db: Session, row: AssistantMessage, index: int, **fields: Any) -> None:
    items = [dict(item) for item in row.buttons or ()]
    items[index] |= fields
    db.execute(
        update(AssistantMessage)
        .where(AssistantMessage.id == row.id)
        .values(buttons=items)
    )
    row.buttons = items


def _question_of(db: Session, *, row: AssistantMessage) -> str:
    """The client's words this answer was written for."""
    asked = db.scalar(
        select(AssistantMessage.text)
        .where(
            AssistantMessage.session_id == row.session_id,
            AssistantMessage.author == Author.USER,
            AssistantMessage.created_at <= row.created_at,
        )
        .order_by(AssistantMessage.created_at.desc())
        .limit(1)
    )
    return str(asked or "")


def _send_ticket(
    db: Session, *, owner: User, row: AssistantMessage, index: int, now: datetime
) -> Pressed:
    """Into the client's support chat and onto Support's board, together:
    the board's card and the message commit as one, so there is never a
    ticket nobody can read or a message nobody was assigned."""
    from app.modules.assistant.services.support import sending_from
    from app.modules.boards.constants import TicketReason
    from app.modules.boards.tickets import raise_ticket
    from app.modules.supportchat.drafts import Draft
    from app.modules.supportchat.exceptions import AlreadySent
    from app.modules.supportchat.live import broadcast_message
    from app.modules.supportchat.services import send_to_support

    item = row.buttons[index]
    key = str(item.get("key", ""))
    if not hit(
        bucket=TICKET_BUCKET,
        key=str(owner.id),
        limit=TICKETS_PER_DAY,
        window_seconds=86400,
    ):
        raise TooManyTickets
    body = ticket_text(
        question=_question_of(db, row=row),
        summary=str(item.get("summary", "")),
        checked=[str(line) for line in item.get("checked", ())],
        answer=row.text,
    )
    thread = db.get(AssistantSession, row.session_id)
    _write(db, row, index, state=ButtonState.SENT, sent_at=now.isoformat())
    raise_ticket(
        db,
        owner_id=owner.id,
        reason=TicketReason.AI,
        ref=f"ai:{row.id}",
        now=now,
        detail=str(item.get("summary", ""))[:500],
    )
    try:
        with sending_from(db, thread=thread, as_row=False):
            sent = send_to_support(
                db,
                owner=owner,
                draft=Draft(body=body, source=MessageSource.AI_CHAT),
                now=now,
                send_key=f"assistant-ticket:{row.id}:{key}",
            )
    except AlreadySent:
        db.commit()
        return Pressed(
            kind=ButtonKind.TICKET, key=key, state=ButtonState.SENT, text=SENT_WORDS
        )
    broadcast_message(message=sent)
    logger.info("assistant_ticket_sent", extra={"owner_id": str(owner.id)})
    return Pressed(
        kind=ButtonKind.TICKET, key=key, state=ButtonState.SENT, text=SENT_WORDS
    )


def _ticket_state(db: Session, *, owner: User, key: str) -> Pressed:
    """The board's column, in the three words the button shows."""
    from app.modules.boards.constants import Board, SupportColumn
    from app.modules.boards.models import BoardCard

    column = db.scalar(
        select(BoardCard.column_code).where(
            BoardCard.board == str(Board.SUPPORT), BoardCard.owner_id == owner.id
        )
    )
    if column in (SupportColumn.RESOLVED, SupportColumn.CLOSED):
        return Pressed(
            kind=ButtonKind.TICKET, key=key, state=ButtonState.DONE, text=RESOLVED_WORDS
        )
    if column in (
        SupportColumn.IN_PROGRESS,
        SupportColumn.DEVELOPER,
        SupportColumn.CONFIRMING,
    ):
        return Pressed(
            kind=ButtonKind.TICKET,
            key=key,
            state=ButtonState.WORKING,
            text=WORKING_TICKET,
        )
    return Pressed(
        kind=ButtonKind.TICKET, key=key, state=ButtonState.SENT, text=SENT_WORDS
    )


def _confirm_change(
    db: Session, *, owner: User, row: AssistantMessage, index: int
) -> Pressed:
    """The Reklama screen's own service, which checks everything again."""
    from app.modules.ads import actions
    from app.modules.chat.services.changes import _ask
    from app.modules.notifications.services.refusals import refusal_words

    item = row.buttons[index]
    key = str(item.get("key", ""))
    try:
        log = actions.request(
            db,
            user=owner,
            ask=_ask(
                str(item["action"]), str(item["level"]), str(item["external_id"]), item
            ),
        )
    except DomainError as exc:
        db.rollback()
        return Pressed(
            kind=ButtonKind.CHANGE,
            key=key,
            state=ButtonState.REFUSED,
            text=str(refusal_words(exc)),
        )
    _write(db, row, index, state=ButtonState.SENT, log_id=str(log.id))
    return Pressed(
        kind=ButtonKind.CHANGE, key=key, state=ButtonState.WORKING, text=WORKING
    )


def _change_state(db: Session, *, owner: User, item: dict[str, Any]) -> Pressed:
    from app.modules.audit.constants import ActionStatus
    from app.modules.audit.models import ActionLog
    from app.modules.chat.services.changes import _refused_words

    key = str(item.get("key", ""))

    def at(state: str, text: str) -> Pressed:
        return Pressed(kind=ButtonKind.CHANGE, key=key, state=state, text=text)

    try:
        log = db.get(ActionLog, uuid.UUID(str(item.get("log_id", ""))))
    except ValueError:
        log = None
    if log is None or log.owner_id != owner.id:
        return at(ButtonState.GONE, GONE_WORDS)
    if log.status == ActionStatus.PENDING:
        return at(ButtonState.WORKING, WORKING)
    if log.status == ActionStatus.APPLIED:
        if (log.result_payload or {}).get("landed") is False:
            return at(ButtonState.DONE, "O'zgarish Meta tomonida ko'rinmadi.")
        return at(ButtonState.DONE, APPLIED)
    return at(ButtonState.REFUSED, _refused_words(db, log=log))


def _approve_offer(
    db: Session, *, owner: User, row: AssistantMessage, index: int
) -> Pressed:
    """The Amallar screen's own service for a proposal of the agent's."""
    from app.modules.agent.selectors import one
    from app.modules.agent.services import approve_suggestion
    from app.modules.notifications.services.refusals import refusal_words

    item = row.buttons[index]
    key = str(item.get("key", ""))

    def at(state: str, text: str) -> Pressed:
        return Pressed(kind=ButtonKind.OFFER, key=key, state=state, text=text)

    suggestion = one(db, owner=owner, pk=str(item.get("pk", "")))
    if suggestion is None:
        return at(ButtonState.GONE, "Bu taklif topilmadi.")
    try:
        approve_suggestion(db, user=owner, suggestion=suggestion)
    except DomainError as exc:
        db.rollback()
        return at(ButtonState.REFUSED, str(refusal_words(exc)))
    _write(db, row, index, state=ButtonState.SENT)
    return at(ButtonState.WORKING, WORKING)


def _offer_state(
    db: Session, *, owner: User, item: dict[str, Any], now: datetime
) -> Pressed:
    from app.modules.agent.selectors import card_for, is_working, one

    key = str(item.get("key", ""))

    def at(state: str, text: str) -> Pressed:
        return Pressed(kind=ButtonKind.OFFER, key=key, state=state, text=text)

    pk = str(item.get("pk", ""))
    suggestion = one(db, owner=owner, pk=pk)
    if suggestion is None:
        return at(ButtonState.GONE, "")
    if is_working(db, owner=owner, pk=pk, now=now):
        return at(ButtonState.WORKING, WORKING)
    card = card_for(db, owner=owner, suggestion=suggestion)
    if card.landed is False:
        return at(ButtonState.DONE, "O'zgarish Meta tomonida ko'rinmadi.")
    return at(ButtonState.DONE, str(card.expectation))


__all__ = [
    "Pressed",
    "TooManyTickets",
    "buttons_of",
    "dismiss",
    "drawn",
    "press",
    "state_of",
    "ticket_text",
]
