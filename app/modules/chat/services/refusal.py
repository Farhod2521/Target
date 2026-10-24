"""Why a launch was refused and what to do about it, answered in the chat."""

import logging
import uuid
from collections.abc import Mapping
from datetime import datetime
from functools import partial
from typing import Any, Final

from llmkit import LLMError, render
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.common.exceptions import LLMUnavailable
from app.common.i18n import get_language, override
from app.common.llm import ASKED, claude, model_for, prompts
from app.modules.accounts.models import User
from app.modules.audit.constants import LLMPurpose
from app.modules.chat.constants import (
    REFUSAL_ANSWER_FIELDS,
    REFUSAL_MAX_TOKENS,
    REFUSAL_PROMPT_NAME,
    REFUSAL_STALE_VERSIONS,
    RELATED_TYPE,
    TURN_TTL_SECONDS,
    ChatMessageStatus,
    ChatRole,
)
from app.modules.chat.copy import ASK_ABOUT_ITEM
from app.modules.chat.exceptions import (
    ChatBudgetSpent,
    ChatNeedsSubscription,
    RefusalNotFound,
)
from app.modules.chat.models import ChatMessage, ChatSession, RefusalAnswer
from app.modules.chat.selectors.refusal import (
    answer_language,
    key_for,
    ready_answer,
    refusal_facts,
    refusal_links,
    refusal_quote,
    refused_launch_for,
)
from app.modules.chat.services.ask import TITLE_CHARS, TURN_KEY, Turn
from app.modules.chat.services.frames import drain, publish
from core.chat.choices import ChoiceGate
from core.chat.links import Link, link_html, link_text
from core.chat.markdown import render as render_markdown
from core.chat.numbers import figures_in
from core.chat.refusal import RefusalFacts, shareable
from core.chat.verify import FigureGate

logger = logging.getLogger(__name__)

ASK: Final = "Explain this refusal and write the steps."


def start_refusal_turn(
    db: Session,
    *,
    owner: User,
    entitled: bool,
    launch_id: str,
    now: datetime,
    session: ChatSession | None = None,
) -> Turn:
    """Check, write the two rows, and leave the turn for the worker."""
    from app.modules.billing.selectors import ai_budget

    launch = refused_launch_for(db, owner=owner, launch_id=launch_id)
    if launch is None:
        raise RefusalNotFound
    language = answer_language(get_language())
    if ready_answer(db, key=key_for(launch), language=language) is None:
        if not entitled:
            raise ChatNeedsSubscription
        if ai_budget(db, owner=owner, now=now).chat_is_exhausted:
            raise ChatBudgetSpent
    question = str(ASK_ABOUT_ITEM)
    quote = refusal_quote(launch)
    thread, message = _record(
        db,
        owner=owner,
        entitled=entitled,
        session=session,
        text=question,
        quote=quote,
        page_id=launch.page_id,
    )
    turn_id = str(uuid.uuid4())
    cache.set(
        TURN_KEY.format(turn_id=turn_id),
        {
            "owner_id": str(owner.id),
            "launch_id": str(launch.id),
            "language": language,
            "message_id": str(message.id) if message is not None else "",
        },
        TURN_TTL_SECONDS,
    )
    return Turn(
        turn_id=turn_id,
        session_id=str(thread.id) if thread is not None else "",
        question=question,
        left=-1,
    )


def answer_refusal(
    db: Session, *, turn_id: str, payload: dict[str, Any], now: datetime
) -> None:
    """The ready answer if there is one; otherwise ask Claude and keep it."""
    owner = None
    try:
        owner = db.get(User, uuid.UUID(str(payload.get("owner_id", ""))))
    except ValueError:
        owner = None
    launch = (
        refused_launch_for(db, owner=owner, launch_id=payload.get("launch_id", ""))
        if owner is not None
        else None
    )
    if owner is None or launch is None:
        _failed(db, turn_id, payload=payload)
        return
    language = answer_language(str(payload.get("language") or ""))
    with override(language):
        key = key_for(launch)
        ready = ready_answer(db, key=key, language=language)
        links = refusal_links(launch)
        if ready is not None:
            db.execute(
                update(RefusalAnswer)
                .where(RefusalAnswer.id == ready.pk)
                .values(hits=RefusalAnswer.hits + 1)
            )
            gate = FigureGate(allowed=figures_in(ready.text))
            _done(
                db,
                turn_id,
                text=ready.text,
                gate=gate,
                payload=payload,
                now=now,
                links=links,
            )
            return
        _ask(
            db,
            turn_id,
            owner=owner,
            launch=launch,
            key=key,
            payload=payload,
            now=now,
            links=links,
        )


def _ask(
    db: Session,
    turn_id: str,
    *,
    owner: User,
    launch: Any,
    key: str,
    payload: dict[str, Any],
    now: datetime,
    links: Mapping[str, Link],
) -> None:
    """One call, streamed to the screen, kept for the next advertiser."""
    from app.modules.audit.services import record_llm_error, record_llm_result

    language = str(payload.get("language") or "")
    facts = refusal_facts(launch)
    gate = FigureGate(allowed=facts.figures())
    template, version = prompts().get(REFUSAL_PROMPT_NAME)
    system = render(template, {"language": language, "facts": facts.render()})
    safe: list[str] = []
    try:
        with claude() as client:
            stream = client.stream(
                prompt=ASK,
                system=system,
                prompt_name=REFUSAL_PROMPT_NAME,
                prompt_version=version,
                max_tokens=REFUSAL_MAX_TOKENS,
            )
            drain(
                stream,
                turn_id=turn_id,
                gate=gate,
                choices=ChoiceGate(),
                payload=payload,
                safe=safe,
                linked=partial(link_html, links=links),
            )
    except LLMUnavailable:
        logger.warning("refusal answer skipped: no Claude in this process")
        _failed(db, turn_id, payload=payload)
        return
    except LLMError as exc:
        logger.warning("refusal answer failed: %s", exc)
        _failed(db, turn_id, payload=payload)
        record_llm_error(
            db,
            owner=owner,
            purpose=LLMPurpose.REFUSAL,
            exc=exc,
            prompt_name=REFUSAL_PROMPT_NAME,
            prompt_version=version,
            model=model_for(ASKED),
            currency=str(settings.anthropic_price_currency),
            related_type=RELATED_TYPE,
            related_id=payload.get("message_id", ""),
        )
        return
    text = "".join(safe).strip()
    _done(db, turn_id, text=text, gate=gate, payload=payload, now=now, links=links)
    record_llm_result(
        db,
        owner=owner,
        purpose=LLMPurpose.REFUSAL,
        result=stream.result,
        masked=gate.masked,
        related_type=RELATED_TYPE,
        related_id=payload.get("message_id", ""),
    )
    if key and text and not gate.masked and shareable(text):
        _keep(db, key=key, language=language, text=text, facts=facts, version=version)


def _keep(
    db: Session,
    *,
    key: str,
    language: str,
    text: str,
    facts: RefusalFacts,
    version: str,
) -> None:
    """Fill this language's column on the refusal's one row."""
    row = db.scalar(select(RefusalAnswer).where(RefusalAnswer.key == key))
    if row is None:
        row = RefusalAnswer(
            key=key,
            provider_title=facts.provider_title,
            provider_message=facts.provider_message,
            prompt_version=version,
        )
        db.add(row)
        db.flush()
    field = REFUSAL_ANSWER_FIELDS[answer_language(language)]
    column = getattr(RefusalAnswer, field)
    db.execute(
        update(RefusalAnswer)
        .where(
            RefusalAnswer.id == row.id,
            RefusalAnswer.prompt_version.in_(list(REFUSAL_STALE_VERSIONS)),
        )
        .values(
            **(dict.fromkeys(REFUSAL_ANSWER_FIELDS.values(), "") | {field: text}),
            prompt_version=version,
            provider_title=facts.provider_title,
            provider_message=facts.provider_message,
            hits=RefusalAnswer.hits + 1,
        )
    )
    db.execute(
        update(RefusalAnswer)
        .where(RefusalAnswer.id == row.id, column == "")
        .values(**{field: text}, hits=RefusalAnswer.hits + 1)
    )


def _record(
    db: Session,
    *,
    owner: User,
    entitled: bool,
    session: ChatSession | None,
    text: str,
    quote: dict[str, str],
    page_id: Any,
) -> tuple[ChatSession | None, ChatMessage | None]:
    """The question and an empty answer, for an account that keeps history."""
    if not entitled:
        return None, None
    thread = session
    if thread is None:
        thread = ChatSession(
            owner_id=owner.id, title=quote["title"][:TITLE_CHARS], page_id=page_id
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


def _message_key(payload: dict[str, Any]) -> uuid.UUID | None:
    raw = payload.get("message_id", "")
    try:
        return uuid.UUID(str(raw)) if raw else None
    except ValueError:
        return None


def _done(
    db: Session,
    turn_id: str,
    *,
    text: str,
    gate: FigureGate,
    payload: dict[str, Any],
    now: datetime,
    links: Mapping[str, Link],
) -> None:
    """The last frame, then the row - the screen is not kept waiting on it."""
    publish(
        turn_id,
        text,
        gate=gate,
        payload=payload,
        done=True,
        linked=partial(link_html, links=links),
    )
    key = _message_key(payload)
    if key is None:
        return
    session_id = db.scalar(select(ChatMessage.session_id).where(ChatMessage.id == key))
    if session_id is None:
        return
    db.execute(
        update(ChatMessage)
        .where(ChatMessage.id == key)
        .values(
            text=link_text(text, links),
            html=link_html(render_markdown(text), links),
            status=ChatMessageStatus.DONE,
            masked_figures=gate.masked,
            updated_at=now,
        )
    )
    db.execute(
        update(ChatSession)
        .where(ChatSession.id == session_id)
        .values(last_message_at=now)
    )


def _failed(db: Session, turn_id: str, *, payload: dict[str, Any]) -> None:
    publish(
        turn_id,
        "",
        gate=FigureGate(allowed=frozenset()),
        payload=payload,
        done=True,
        error="failed",
    )
    key = _message_key(payload)
    if key is not None:
        db.execute(
            update(ChatMessage)
            .where(ChatMessage.id == key)
            .values(status=ChatMessageStatus.FAILED)
        )


__all__ = ["answer_refusal", "start_refusal_turn"]
