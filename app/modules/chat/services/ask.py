"""Accepting one question: the checks, the record, and the handover."""

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Final

from llmkit import render
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.i18n import get_language
from app.common.llm import prompts
from app.modules.accounts.models import User
from app.modules.chat.constants import (
    ANSWER_MAX_TOKENS,
    MAX_QUESTION_CHARS,
    PROMPT_NAME,
    TURN_TTL_SECONDS,
    ChatMessageStatus,
    ChatRole,
)
from app.modules.chat.copy import ASK_ABOUT_ITEM
from app.modules.chat.exceptions import (
    ChatBudgetSpent,
    ChatNeedsSubscription,
    ChatQuestionsSpent,
    FreeQuestionsSpent,
    QuestionTooLong,
)
from app.modules.chat.models import ChatMessage, ChatSession
from app.modules.chat.selectors.choices import offers_for
from app.modules.chat.selectors.context import chat_context
from app.modules.chat.selectors.scope import current_page_scope
from app.modules.chat.selectors.sessions import history
from app.modules.chat.services.quota import Allowance, allowance, consume
from core.chat.numbers import figures_in
from core.chat.route import route

TURN_KEY: Final = "chat:turn:{turn_id}"
TITLE_CHARS: Final = 60


@dataclass(frozen=True, slots=True)
class QuestionCount:
    """What the line under the box says: how many are left, out of how many."""

    left: int
    total: int


@dataclass(frozen=True, slots=True)
class Turn:
    """What the browser needs to start listening for the answer."""

    turn_id: str
    session_id: str
    question: str
    left: int


def start_turn(
    db: Session,
    *,
    question: str,
    owner: User | None,
    entitled: bool,
    scope: str,
    now: datetime,
    session: ChatSession | None = None,
    asked: tuple[str, ...] = (),
    focus_id: str = "",
    item_key: str = "",
) -> Turn:
    """Check, record, and hand a prepared turn to the worker."""
    text = question.strip() or (str(ASK_ABOUT_ITEM) if item_key else "")
    if len(text) > MAX_QUESTION_CHARS:
        raise QuestionTooLong(MAX_QUESTION_CHARS)
    left = _check_allowance(db, owner=owner, entitled=entitled, scope=scope, now=now)

    said = (
        list(history(db, owner=owner, session=session))
        if session is not None and owner is not None
        else list(asked_as_history(asked))
    )
    wants = route(question=text, previous=_their_own(said)).wants
    page = (
        current_page_scope(db, owner=owner) if entitled and owner is not None else None
    )
    offers = offers_for(
        db, owner=owner, entitled=entitled, wants=wants, now=now, scope=page
    )
    context = chat_context(
        db,
        owner=owner if entitled else None,
        asked=asked,
        focus_id=focus_id,
        item_key=item_key,
        wants=wants,
        offers=offers,
        now=now,
        scope=page,
    )
    turn_id = str(uuid.uuid4())
    thread, message = _record(
        db,
        owner=owner,
        entitled=entitled,
        session=session,
        text=text,
        quote=context.quote(),
    )
    template, version = prompts().get(PROMPT_NAME)
    language = get_language() or ""
    cache.set(
        TURN_KEY.format(turn_id=turn_id),
        {
            "question": text,
            "system": render(template, {"language": language, "context": ""}).rstrip(),
            "system_tail": context.render(),
            "history": said,
            "figures": sorted(context.figures()),
            "quoted": sorted(context.quoted | _said_figures(text=text, said=said)),
            "owner_id": str(owner.id) if owner is not None else "",
            "message_id": str(message.id) if message is not None else "",
            "prompt_version": version,
            "language": language,
            "max_tokens": ANSWER_MAX_TOKENS,
            "offers": [asdict(item) for item in offers],
            "lookups": entitled and owner is not None,
        },
        TURN_TTL_SECONDS,
    )
    return Turn(
        turn_id=turn_id,
        session_id=str(thread.id) if thread is not None else "",
        question=text,
        left=left,
    )


def asked_as_history(asked: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """A visitor's own turns, which live in their browser session only."""
    return tuple(("user", item) for item in asked)


def _said_figures(*, text: str, said: list[tuple[str, str]]) -> frozenset[str]:
    return figures_in(" ".join([text, *(content for _role, content in said)]))


def _their_own(said: list[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(text for role, text in said if role == ChatRole.USER)


def _check_allowance(
    db: Session, *, owner: User | None, entitled: bool, scope: str, now: datetime
) -> int:
    """Three ceilings and a gate. A visitor meets one; a subscriber two."""
    from app.modules.billing.selectors import ai_budget, chat_allowance

    if owner is not None and not entitled:
        raise ChatNeedsSubscription
    if owner is None:
        spent: Allowance = consume(scope=scope)
        if spent.used > spent.limit:
            raise FreeQuestionsSpent
        return spent.remaining
    allowed = chat_allowance(db, owner=owner, now=now)
    if allowed.is_exhausted:
        raise ChatQuestionsSpent(limit=allowed.limit)
    if ai_budget(db, owner=owner, now=now).chat_is_exhausted:
        raise ChatBudgetSpent
    return allowed.remaining


def _record(
    db: Session,
    *,
    owner: User | None,
    entitled: bool,
    session: ChatSession | None,
    text: str,
    quote: dict[str, str],
) -> tuple[ChatSession | None, ChatMessage | None]:
    """Rows for a subscriber, nothing for anybody else."""
    from app.modules.integrations.selectors import active_ad_account, active_page

    if not entitled or owner is None:
        return None, None
    thread = session
    if thread is None:
        page = active_page(db, owner=owner)
        account = active_ad_account(db, owner=owner)
        thread = ChatSession(
            owner_id=owner.id,
            title=(quote.get("title") or text)[:TITLE_CHARS],
            page_id=page.id if page is not None else None,
            ad_account_id=account.id if account is not None else None,
        )
        db.add(thread)
        db.flush()
    db.add(
        ChatMessage(
            owner_id=owner.id,
            session_id=thread.id,
            role=ChatRole.USER,
            text=text,
            quote=quote,
        )
    )
    db.flush()
    answer = ChatMessage(
        owner_id=owner.id,
        session_id=thread.id,
        role=ChatRole.ASSISTANT,
        status=ChatMessageStatus.PENDING,
    )
    db.add(answer)
    db.flush()
    return thread, answer


def turn_payload(*, turn_id: str) -> dict[str, Any] | None:
    """The prepared turn, or nothing if it expired before a worker got it."""
    value = cache.get(TURN_KEY.format(turn_id=turn_id))
    return value if isinstance(value, dict) else None


def remaining_for(*, scope: str) -> int:
    """What the line under the box says. Read-only; asking costs nothing."""
    return allowance(scope=scope).remaining


def questions_left_for(
    db: Session, *, owner: User, entitled: bool, now: datetime
) -> QuestionCount:
    """The figures under the box for a signed-in reader."""
    from app.modules.billing.selectors import chat_allowance

    if entitled:
        allowed = chat_allowance(db, owner=owner, now=now)
        return QuestionCount(left=allowed.remaining, total=allowed.limit)
    return QuestionCount(left=0, total=0)


__all__ = [
    "TURN_KEY",
    "QuestionCount",
    "Turn",
    "asked_as_history",
    "questions_left_for",
    "remaining_for",
    "start_turn",
    "turn_payload",
]
