"""An answer that could not help hands the question to a person in Support.

The model ends such an answer with ``%%SUPPORT%%`` (``core/chat/choices.py``).
For an owner the question is written into their own support chat, as if
they had sent it, and the support chat's own hook copies it to every member
of Support on the staff bot. A visitor has no support chat and no account
to write it under: the question waits in the cache under the turn, and the
page asks for a name and a phone (``POST /chat/handoff``) before a guest chat
is opened with it.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.exceptions import DomainError
from app.common.throttle import hit
from app.modules.accounts.models import User
from app.modules.supportchat.constants import MAX_BODY_CHARS, MessageSource

logger = logging.getLogger(__name__)


class HandoffState:
    """What the page is told under the answer (``handoff`` in the frame)."""

    # Written into the owner's support chat; Support has it in Telegram.
    SENT = "sent"
    # A visitor: show the name-and-phone form for ``POST /chat/handoff``.
    ASK_PHONE = "ask_phone"
    # Too many in the hour, or the support chat refused it: point at Support.
    NOT_SENT = "not_sent"


HANDOFF_KIND: Final = "handoff"
WAITING_KEY: Final = "chat:handoff:{turn_id}"
# Long enough to read the answer, go and find the phone, and come back.
WAITING_SECONDS: Final = 24 * 3600
CLAIM_KEY: Final = "chat:handoff:{turn_id}:claim"
CLAIM_SECONDS: Final = 120
BUCKET: Final = "chat-handoff"
PER_HOUR: Final = 3
ANSWER_CHARS: Final = 600
HEADER: Final = "🤖 AI yordamchi bu savolga javob topa olmadi."


@dataclass(frozen=True, slots=True)
class Waiting:
    """A visitor's question, kept until they leave a phone for it."""

    question: str
    answer: str


def hand_over(
    db: Session,
    *,
    turn_id: str,
    owner: User | None,
    payload: dict[str, Any],
    answer: str,
    now: datetime,
) -> str:
    """Send the question on, or keep it for the visitor's phone. Returns the
    ``HandoffState`` the page shows. Never raises: the answer has been
    written either way, and a handover that fails must not lose it."""
    question = str(payload.get("question", "")).strip()
    if not question:
        return ""
    if not payload.get("owner_id") or owner is None:
        try:
            cache.set(
                WAITING_KEY.format(turn_id=turn_id),
                {"question": question, "answer": answer},
                WAITING_SECONDS,
            )
        except Exception:
            logger.exception("chat_handoff_not_kept")
            return HandoffState.NOT_SENT
        return HandoffState.ASK_PHONE
    if not hit(bucket=BUCKET, key=str(owner.id), limit=PER_HOUR, window_seconds=3600):
        logger.info("chat_handoff_throttled", extra={"owner_id": str(owner.id)})
        return HandoffState.NOT_SENT
    return _send(
        db,
        owner=owner,
        body=handoff_text(question=question, answer=answer),
        key=f"ai-handoff:{payload.get('message_id') or turn_id}",
        now=now,
    )


def _send(db: Session, *, owner: User, body: str, key: str, now: datetime) -> str:
    from app.modules.supportchat.drafts import Draft
    from app.modules.supportchat.exceptions import AlreadySent
    from app.modules.supportchat.services import send_to_support

    try:
        send_to_support(
            db,
            owner=owner,
            draft=Draft(body=body, source=MessageSource.AI_CHAT),
            now=now,
            send_key=key,
        )
    except AlreadySent:
        return HandoffState.SENT
    except DomainError:
        logger.warning("chat_handoff_refused", exc_info=True)
        return HandoffState.NOT_SENT
    except Exception:
        # The answer is still to be published and stored after this.
        logger.exception("chat_handoff_failed")
        db.rollback()
        return HandoffState.NOT_SENT
    logger.info("chat_handoff_sent", extra={"owner_id": str(owner.id)})
    return HandoffState.SENT


def handoff_text(*, question: str, answer: str) -> str:
    """What Support reads: the question, and what the assistant already said."""
    said = " ".join(answer.split())
    if len(said) > ANSWER_CHARS:
        said = said[: ANSWER_CHARS - 1].rstrip() + "…"
    parts = [HEADER, "", f"Savol: {question}"]
    if said:
        parts += ["", f"AI javobi: {said}"]
    return "\n".join(parts)[:MAX_BODY_CHARS]


def waiting_for(turn_id: str) -> Waiting | None:
    """The visitor's question this turn kept, if it is still waiting."""
    value = cache.get(WAITING_KEY.format(turn_id=turn_id))
    if not isinstance(value, dict) or not value.get("question"):
        return None
    return Waiting(question=str(value["question"]), answer=str(value.get("answer", "")))


def claim(turn_id: str) -> bool:
    """Only one ``POST /chat/handoff`` at a time opens a chat for a kept
    question: a double click or a retry gets False."""
    return cache.add(CLAIM_KEY.format(turn_id=turn_id), "1", CLAIM_SECONDS)


def release(turn_id: str) -> None:
    """The guest chat did not open: the visitor may send the form again."""
    cache.delete(CLAIM_KEY.format(turn_id=turn_id))


def forget(turn_id: str) -> None:
    """One guest chat per kept question."""
    cache.delete(WAITING_KEY.format(turn_id=turn_id))


def handoff_item(state: str) -> dict[str, str]:
    """The state as it is stored on the answer's row."""
    return {"kind": HANDOFF_KIND, "state": state}


def handoff_in(choices: Any) -> str:
    """The stored state on one answer's row, or empty."""
    for item in choices or ():
        if isinstance(item, dict) and item.get("kind") == HANDOFF_KIND:
            return str(item.get("state", ""))
    return ""


__all__ = [
    "HANDOFF_KIND",
    "HandoffState",
    "Waiting",
    "claim",
    "forget",
    "hand_over",
    "handoff_in",
    "handoff_item",
    "handoff_text",
    "release",
    "waiting_for",
]
