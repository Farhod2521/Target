"""The client's request to Support, as the assistant may speak of it.

Support often settles a request by phone and writes nothing in the chat, so
the chat alone cannot tell the assistant what is going on: without this it
told a client «the answer is in the Yordam chat» when nothing was there, and
prepared a second request for a problem a specialist already had in hand.

Read-only. The office's own notes are words for colleagues; only the note a
specialist left when they marked the request solved is passed on, as what
was done - never to be quoted.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.boards.constants import Board, EventKind, SupportColumn

# A request solved this recently is still worth a line: «it was solved
# yesterday» answers «is it still broken?».
RECENT_DONE: Final = timedelta(days=3)
TOPICS: Final = 3
TOPIC_CHARS: Final = 160
NOTE_CHARS: Final = 200

# Support has it in hand: a second request for the same problem only adds
# a line to this one, so the assistant is told so first.
IN_HAND: Final = frozenset(
    {
        str(SupportColumn.NEW),
        str(SupportColumn.IN_PROGRESS),
        str(SupportColumn.DEVELOPER),
    }
)

_STATE: Final = {
    str(SupportColumn.NEW): (
        "it is in Support's queue; no specialist has taken it yet."
    ),
    str(SupportColumn.IN_PROGRESS): "a specialist is working on it.",
    str(SupportColumn.DEVELOPER): (
        "a specialist passed it to the developers; it is being fixed."
    ),
    str(SupportColumn.WAITING): (
        "the specialist did their part and waits for the client's answer or action."
    ),
    str(SupportColumn.UNREACHABLE): (
        "the specialist could not reach the client by phone or Telegram."
    ),
    str(SupportColumn.CONFIRMING): (
        "the specialist marked it solved; the client was asked whether it is."
    ),
    str(SupportColumn.RESOLVED): "it was solved and the client confirmed it.",
    str(SupportColumn.CLOSED): (
        "it was marked solved; the client did not answer whether it is."
    ),
}


@dataclass(frozen=True)
class SupportRequest:
    column: str
    opened_at: datetime
    column_since: datetime
    topics: tuple[str, ...]
    solved_note: str
    wrote_in_chat: bool

    @property
    def in_hand(self) -> bool:
        return self.column in IN_HAND


def support_request(
    db: Session, *, owner: User, now: datetime
) -> SupportRequest | None:
    """The client's request, open or solved lately; ``None`` otherwise."""
    from app.modules.boards.models import BoardCard, BoardCardEvent
    from app.modules.supportchat.selectors import chat_of

    card = db.scalar(
        select(BoardCard).where(
            BoardCard.board == str(Board.SUPPORT),
            BoardCard.owner_id == owner.id,
            BoardCard.term_ends_at.is_(None),
        )
    )
    if card is None:
        return None
    done = card.column_code in (str(SupportColumn.RESOLVED), str(SupportColumn.CLOSED))
    if done and now - card.column_since > RECENT_DONE:
        return None
    topics = tuple(
        " ".join(str(item.get("detail", "")).split())[:TOPIC_CHARS]
        for item in reversed(card.reasons or [])
        if str(item.get("detail", "")).strip()
    )[:TOPICS]
    note = ""
    if card.column_code in (
        str(SupportColumn.CONFIRMING),
        str(SupportColumn.RESOLVED),
        str(SupportColumn.CLOSED),
    ):
        note = (
            db.scalar(
                select(BoardCardEvent.body)
                .where(
                    BoardCardEvent.card_id == card.id,
                    BoardCardEvent.kind == str(EventKind.RESOLVED),
                )
                .order_by(BoardCardEvent.created_at.desc())
                .limit(1)
            )
            or ""
        )
    chat = chat_of(db, owner=owner)
    since = _round_started(db, card_id=card.id) or card.opened_at
    wrote = (
        chat is not None
        and chat.last_office_at is not None
        and chat.last_office_at >= since
    )
    return SupportRequest(
        column=card.column_code,
        opened_at=card.opened_at,
        column_since=card.column_since,
        topics=topics,
        solved_note=" ".join(note.split())[:NOTE_CHARS],
        wrote_in_chat=wrote,
    )


def _round_started(db: Session, *, card_id: object) -> datetime | None:
    """When this round began: the card's last reopening, if any."""
    from app.modules.boards.models import BoardCardEvent

    return db.scalar(
        select(BoardCardEvent.created_at)
        .where(
            BoardCardEvent.card_id == card_id,
            BoardCardEvent.kind == str(EventKind.REOPENED),
        )
        .order_by(BoardCardEvent.created_at.desc())
        .limit(1)
    )


def ago(moment: datetime, *, now: datetime) -> str:
    """«3 hours ago», «2 days ago» - no clock, so no time zone to get wrong."""
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 3600:
        return f"{max(1, seconds // 60)} minutes ago"
    if seconds < 2 * 86400:
        return f"{seconds // 3600} hours ago"
    return f"{seconds // 86400} days ago"


def request_lines(request: SupportRequest | None, *, now: datetime) -> list[str]:
    """The request as the health check's lines, each one fact."""
    if request is None:
        return ["- OK: no request to Support is open."]
    state = _STATE.get(request.column, f"its state is {request.column}.")
    lines = [
        f"- OK: a request to Support, opened {ago(request.opened_at, now=now)}: "
        f"{state} (since {ago(request.column_since, now=now)})"
    ]
    for topic in request.topics:
        lines.append(f"  - about: {topic}")
    if request.solved_note:
        lines.append(
            "  - what the specialist did (their own words for colleagues - "
            f"say it in your words, never quote): {request.solved_note}"
        )
    if not request.wrote_in_chat:
        lines.append(
            "  - Support has written nothing in this chat for this request: "
            "they usually call the client. Never say a reply is waiting in "
            "the chat."
        )
    if request.in_hand:
        lines.append(
            "  - Support already has it: for the same problem, say so and "
            "prepare no new request."
        )
    return lines


__all__ = [
    "IN_HAND",
    "SupportRequest",
    "ago",
    "request_lines",
    "support_request",
]
