"""Accepting one question: the checks, the rows, and the handover to a worker.

The account's context, the page it is scoped to, the agent's open proposals
and the quota are the old chat's own selectors, used as they are - a figure
quoted here is the figure quoted there. What differs is what the model is
told (``core/assistant/prompt.py``) and where the turn is kept.
"""

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from llmkit import render
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.i18n import get_language
from app.common.llm import prompts
from app.modules.accounts.models import User
from app.modules.assistant.constants import (
    ANSWER_MAX_TOKENS,
    HISTORY_TURNS,
    MAX_QUESTION_CHARS,
    PROMPT_NAME,
    TITLE_CHARS,
    TURN_KEY,
    TURN_TTL_SECONDS,
    Author,
    MessageStatus,
)
from app.modules.assistant.models import AssistantMessage, AssistantSession
from app.modules.assistant.selectors.threads import history, turns
from app.modules.chat.copy import ASK_ABOUT_ITEM
from app.modules.chat.exceptions import (
    ChatBudgetSpent,
    ChatNeedsSubscription,
    ChatQuestionsSpent,
    FreeQuestionsSpent,
    QuestionTooLong,
)
from core.assistant.prompt import language_name, sections_for, split
from core.chat.numbers import figures_in
from core.chat.route import route


@dataclass(frozen=True, slots=True)
class Turn:
    """What the page needs to start listening for the answer."""

    turn_id: str
    session_id: str
    message_id: str
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
    session: AssistantSession | None = None,
    asked: tuple[str, ...] = (),
    focus_id: str = "",
    item_key: str = "",
) -> Turn:
    """Check, record, and hand a prepared turn to the worker."""
    from app.modules.chat.selectors.choices import offers_for
    from app.modules.chat.selectors.context import chat_context
    from app.modules.chat.selectors.scope import current_page_scope

    text = question.strip() or (str(ASK_ABOUT_ITEM) if item_key else "")
    if len(text) > MAX_QUESTION_CHARS:
        raise QuestionTooLong(MAX_QUESTION_CHARS)
    left = _allowance(db, owner=owner, entitled=entitled, scope=scope, now=now)

    said = (
        list(history(db, owner=owner, session=session))
        if session is not None and owner is not None
        else list(turns(tuple(("user", item) for item in asked[-HISTORY_TURNS:])))
    )
    theirs = tuple(words for role, words in said if role == "user")
    wants = route(question=text, previous=theirs).wants
    member = owner if entitled else None
    page = current_page_scope(db, owner=member) if member is not None else None
    offers = offers_for(
        db, owner=owner, entitled=entitled, wants=wants, now=now, scope=page
    )
    context = chat_context(
        db,
        owner=member,
        asked=asked,
        focus_id=focus_id,
        item_key=item_key,
        wants=wants,
        offers=offers,
        now=now,
        scope=page,
    )
    thread, answer = _record(
        db, owner=member, session=session, text=text, quote=context.quote(), now=now
    )
    template, version = prompts().get(PROMPT_NAME)
    prompt = split(template)
    language = get_language() or ""
    drawn = context.render()
    turn_id = str(uuid.uuid4())
    cache.set(
        TURN_KEY.format(turn_id=turn_id),
        {
            "question": text,
            "system": render(prompt.base, {"language": language_name(language)}),
            "system_tail": render(
                prompt.tail(
                    sections_for(
                        context=drawn,
                        question=text,
                        said=theirs,
                        visitor=member is None,
                    ),
                    context=drawn,
                ),
                {"language": language_name(language)},
            ),
            "history": said,
            "figures": sorted(context.figures()),
            "quoted": sorted(
                context.quoted
                | figures_in(" ".join([text, *(words for _role, words in said)]))
            ),
            "owner_id": str(member.id) if member is not None else "",
            "message_id": str(answer.id) if answer is not None else "",
            "session_id": str(thread.id) if thread is not None else "",
            "prompt_version": version,
            "language": language,
            "max_tokens": ANSWER_MAX_TOKENS,
            "offers": [asdict(item) for item in offers],
        },
        TURN_TTL_SECONDS,
    )
    return Turn(
        turn_id=turn_id,
        session_id=str(thread.id) if thread is not None else "",
        message_id=str(answer.id) if answer is not None else "",
        question=text,
        left=left,
    )


def turn_payload(*, turn_id: str) -> dict[str, Any] | None:
    """The prepared turn, or nothing if it expired before a worker got it."""
    value = cache.get(TURN_KEY.format(turn_id=turn_id))
    return value if isinstance(value, dict) else None


def questions_left(
    db: Session, *, owner: User, entitled: bool, now: datetime
) -> tuple[int, int]:
    """``(left, total)`` for the line under the box. Asking costs nothing."""
    from app.modules.billing.selectors import chat_allowance

    if not entitled:
        return 0, 0
    allowed = chat_allowance(db, owner=owner, now=now)
    return allowed.remaining, allowed.limit


def _allowance(
    db: Session, *, owner: User | None, entitled: bool, scope: str, now: datetime
) -> int:
    """The old chat's own ceilings: one quota for both chats, counted on the
    same ledger. A visitor meets the free allowance; a subscriber the plan's
    daily questions and the month's budget."""
    from app.modules.billing.selectors import ai_budget, chat_allowance
    from app.modules.chat.services.quota import consume

    if owner is not None and not entitled:
        raise ChatNeedsSubscription
    if owner is None:
        spent = consume(scope=scope)
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
    session: AssistantSession | None,
    text: str,
    quote: dict[str, str],
    now: datetime,
) -> tuple[AssistantSession | None, AssistantMessage | None]:
    """Rows for a subscriber, nothing for a visitor: the question, and the
    answer's row waiting to be filled."""
    from app.modules.integrations.selectors import active_ad_account, active_page

    if owner is None:
        return None, None
    thread = session
    if thread is None:
        page = active_page(db, owner=owner)
        account = active_ad_account(db, owner=owner)
        thread = AssistantSession(
            owner_id=owner.id,
            title=(quote.get("title") or text)[:TITLE_CHARS],
            page_id=page.id if page is not None else None,
            ad_account_id=account.id if account is not None else None,
        )
        db.add(thread)
        db.flush()
    thread.last_message_at = now
    db.add(
        AssistantMessage(
            owner_id=owner.id,
            session_id=thread.id,
            author=Author.USER,
            text=text,
            status=MessageStatus.DONE,
            meta={"quote": quote} if quote else {},
            created_at=now,
        )
    )
    db.flush()
    answer = AssistantMessage(
        owner_id=owner.id,
        session_id=thread.id,
        author=Author.AI,
        status=MessageStatus.PENDING,
    )
    db.add(answer)
    db.flush()
    return thread, answer


__all__ = ["Turn", "questions_left", "start_turn", "turn_payload"]
