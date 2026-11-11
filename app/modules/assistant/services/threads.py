"""What the client does to a thread itself: give it a name, take it away,
and stop an answer that is being written."""

from typing import Final

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.exceptions import Conflict, DomainError
from app.modules.assistant.constants import (
    OUT_KEY,
    STOP_KEY,
    TITLE_CHARS,
    TURN_KEY,
    TURN_TTL_SECONDS,
)
from app.modules.assistant.models import AssistantMessage, AssistantSession

KEEPS_SUPPORT: Final = (
    "Bu suhbatda Support bilan yozishma bor, uni o'chirib bo'lmaydi. "
    "Nomini o'zgartirishingiz mumkin."
)
NO_TITLE: Final = "Suhbat nomi bo'sh bo'lmasin."


class ThreadKeepsSupport(Conflict):
    """Support's replies land in this thread; taking it away would bring the
    support chat back as a new «Yordam» thread on the next visit."""

    code = "assistant_thread_has_support"

    def __init__(self) -> None:
        super().__init__(KEEPS_SUPPORT)


class EmptyTitle(DomainError):
    status_code = 422
    code = "assistant_thread_title_empty"

    def __init__(self) -> None:
        super().__init__(NO_TITLE)


def rename(db: Session, *, thread: AssistantSession, title: str) -> AssistantSession:
    """The client's own name for the thread, as the rail shows it."""
    words = " ".join(title.split())[:TITLE_CHARS]
    if not words:
        raise EmptyTitle
    thread.title = words
    db.flush()
    return thread


def remove(db: Session, *, thread: AssistantSession) -> None:
    """The thread and its rows go. A thread Support is part of stays: the
    support chat's copy of it is the client's record with the office."""
    if thread.support_at is not None:
        raise ThreadKeepsSupport
    db.execute(delete(AssistantMessage).where(AssistantMessage.session_id == thread.id))
    db.delete(thread)
    db.flush()


def stop(*, turn_id: str, viewer: str) -> bool:
    """Ask the answer being written to end where it is. False when there is
    nothing to stop: it is finished, gone, or someone else's."""
    state = cache.get(OUT_KEY.format(turn_id=turn_id))
    if isinstance(state, dict):
        owner_id = str(state.get("owner_id", ""))
        if owner_id and owner_id != viewer:
            return False
        if state.get("done"):
            return False
    else:
        payload = cache.get(TURN_KEY.format(turn_id=turn_id))
        if not isinstance(payload, dict):
            return False
        owner_id = str(payload.get("owner_id", ""))
        if owner_id and owner_id != viewer:
            return False
    cache.set(STOP_KEY.format(turn_id=turn_id), True, TURN_TTL_SECONDS)
    return True


def stop_asked(turn_id: str) -> bool:
    """Whether the client pressed stop. A cache that cannot be read never
    stops an answer."""
    try:
        return bool(cache.get(STOP_KEY.format(turn_id=turn_id)))
    except Exception:
        return False


__all__ = [
    "EmptyTitle",
    "ThreadKeepsSupport",
    "remove",
    "rename",
    "stop",
    "stop_asked",
]
