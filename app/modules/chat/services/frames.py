"""One answer as the browser receives it: frames in the cache, and what fills them."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from llmkit import TextStream, ToolStream
from sqlalchemy import and_, delete, or_, update
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.modules.chat.constants import (
    ANSWER_STUCK_AFTER_MINUTES,
    SESSION_TTL_DAYS,
    STREAM_CHUNK_CHARS,
    TURN_TTL_SECONDS,
    ChatMessageStatus,
    ChatRole,
)
from app.modules.chat.models import ChatMessage, ChatSession
from core.chat.choices import ChoiceGate
from core.chat.markdown import render
from core.chat.verify import FigureGate

logger = logging.getLogger(__name__)

OUT_KEY: Final = "chat:out:{turn_id}"


@dataclass(frozen=True, slots=True)
class Frame:
    """What the browser is handed. A dict in the cache; this names it."""

    html: str
    done: bool
    error: str
    masked: int
    owner_id: str
    message_id: str
    choices: list[dict[str, str]]
    replies: list[str]
    status: str


def publish(
    turn_id: str,
    text: str,
    *,
    gate: FigureGate,
    payload: dict[str, Any],
    done: bool = False,
    error: str = "",
    choices: list[dict[str, str]] | None = None,
    replies: list[str] | None = None,
    status: str = "",
    linked: Callable[[str], str] | None = None,
) -> None:
    html = render(text)
    cache.set(
        OUT_KEY.format(turn_id=turn_id),
        {
            "html": linked(html) if linked is not None else html,
            "done": done,
            "error": error,
            "masked": gate.masked,
            "owner_id": payload.get("owner_id", ""),
            "message_id": payload.get("message_id", ""),
            "choices": choices or [],
            "replies": replies or [],
            "status": status,
        },
        TURN_TTL_SECONDS,
    )


def announcer(
    turn_id: str,
    *,
    gate: FigureGate,
    payload: dict[str, Any],
    safe: list[str],
    working: Callable[[], None] | None,
) -> Callable[[str], None]:
    """What to call when a look-up starts, for whoever is waiting."""

    def announce(words: str) -> None:
        publish(turn_id, "".join(safe), gate=gate, payload=payload, status=words)
        if working is not None:
            working()

    return announce


def drain(
    stream: TextStream | ToolStream,
    *,
    turn_id: str,
    gate: FigureGate,
    choices: ChoiceGate,
    payload: dict[str, Any],
    safe: list[str],
    linked: Callable[[str], str] | None = None,
) -> None:
    """Read the model's output into ``safe``, publishing as it fills."""
    pending = 0
    for piece in stream:
        safe.append(gate.feed(choices.feed(piece)))
        pending += len(piece)
        if pending >= STREAM_CHUNK_CHARS:
            publish(turn_id, "".join(safe), gate=gate, payload=payload, linked=linked)
            pending = 0
    safe.append(gate.feed(choices.flush()))
    safe.append(gate.flush())


def sweep_old_sessions(db: Session, *, now: datetime) -> int:
    """Forget threads nobody came back to. Returns how many went."""
    cutoff = now - timedelta(days=SESSION_TTL_DAYS)
    stale = or_(
        ChatSession.last_message_at < cutoff,
        and_(ChatSession.last_message_at.is_(None), ChatSession.created_at < cutoff),
    )
    ids = list(
        db.scalars(
            ChatSession.__table__.select()
            .with_only_columns(ChatSession.id)
            .where(stale)
        )
    )
    if not ids:
        return 0
    db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(ids)))
    db.execute(delete(ChatSession).where(ChatSession.id.in_(ids)))
    return len(ids)


def sweep_stuck_answers(db: Session, *, now: datetime) -> int:
    """Close answers no worker will ever write. Returns how many."""
    cutoff = now - timedelta(minutes=ANSWER_STUCK_AFTER_MINUTES)
    closed = db.execute(
        update(ChatMessage)
        .where(
            ChatMessage.role == ChatRole.ASSISTANT,
            ChatMessage.status == ChatMessageStatus.PENDING,
            ChatMessage.created_at < cutoff,
        )
        .values(status=ChatMessageStatus.FAILED, updated_at=now)
    ).rowcount
    if closed:
        logger.warning("chat_answers_stuck", extra={"closed": closed})
    return int(closed or 0)


__all__ = [
    "OUT_KEY",
    "Frame",
    "announcer",
    "drain",
    "publish",
    "sweep_old_sessions",
    "sweep_stuck_answers",
]
