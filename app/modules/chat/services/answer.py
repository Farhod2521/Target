"""Reading Claude's answer, gating it, and publishing it frame by frame."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from llmkit import ClaudeClient, LLMError, TextStream, ToolCall, ToolOutput, ToolStream
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.i18n import override
from app.common.llm import ASKED, claude, model_for
from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.audit.constants import LLMPurpose
from app.modules.chat.constants import (
    LOOKING,
    LOOKING_DEFAULT,
    PROMPT_NAME,
    RELATED_TYPE,
    VISITOR_HEADCOUNT_BELOW,
    ChatMessageStatus,
)
from app.modules.chat.copy import CARRY_ON, CUT_SHORT
from app.modules.chat.models import ChatMessage, ChatSession
from app.modules.chat.selectors.choices import picked
from app.modules.chat.selectors.sessions import reply_items
from app.modules.chat.services.frames import announcer, drain, publish
from app.modules.chat.services.quota import public_chat_owner
from core.chat.choices import ChoiceGate, vetted_replies
from core.chat.lookups import CHANGE_TOOL, MAX_CHANGES, MAX_LOOKUPS, MAX_ROUNDS, TOOLS
from core.chat.markdown import render
from core.chat.numbers import figures_in
from core.chat.verify import FigureGate

logger = logging.getLogger(__name__)

CHANGE_KEY: Final = "P"
PREPARING: Final = "O'zgarishni tayyorlayapman…"

SPENT: Final = (
    "This answer has used all of its look-ups. Answer with what you already have."
)


@dataclass(slots=True)
class LookupDesk:
    """One answer's look-ups: whose account, when, and the gate they widen."""

    db: Session
    owner: User
    now: datetime
    gate: FigureGate
    made: int = 0
    announce: Callable[[str], None] | None = None
    changes: list[dict[str, Any]] = field(default_factory=list)
    _scope: PageScope | None = None
    _counted: PageScope | None = None

    def __call__(self, call: ToolCall) -> ToolOutput:
        from app.modules.chat.selectors.lookups import answer_lookup
        from app.modules.chat.selectors.scope import asked_scopes

        self.made += 1
        if self.made > MAX_LOOKUPS:
            return ToolOutput(text=SPENT, is_error=True)
        if self._scope is None:
            self._scope, self._counted = asked_scopes(self.db, owner=self.owner)
        if call.name == CHANGE_TOOL:
            return self._prepare(call)
        with override(self.owner.language or ""):
            if self.announce is not None:
                self.announce(str(LOOKING.get(call.name, LOOKING_DEFAULT)))
            text = answer_lookup(
                self.db,
                owner=self.owner,
                name=call.name,
                arguments=call.arguments,
                scope=self._scope,
                now=self.now,
                counted=self._counted,
            )
        self.gate.allow(figures_in(text))
        logger.info("chat_lookup", extra={"lookup": call.name, "chars": len(text)})
        return ToolOutput(text=text)

    def _prepare(self, call: ToolCall) -> ToolOutput:
        """A change the owner asked for, checked and described; never carried out here."""
        from app.modules.chat.services.changes import prepare_change

        if len(self.changes) >= MAX_CHANGES:
            return ToolOutput(
                text="This answer already prepared as many changes as one answer may.",
                is_error=True,
            )
        if self.announce is not None:
            self.announce(PREPARING)
        assert self._scope is not None
        prepared = prepare_change(
            self.db,
            owner=self.owner,
            arguments=call.arguments,  # type: ignore[arg-type]
            scope=self._scope,
            key=f"{CHANGE_KEY}{len(self.changes) + 1}",
        )
        if prepared.item is not None:
            self.changes.append(prepared.item)
        self.gate.allow(figures_in(prepared.text))
        logger.info("chat_change", extra={"prepared": prepared.item is not None})
        return ToolOutput(text=prepared.text, is_error=prepared.item is None)


def answer_turn(
    db: Session,
    *,
    turn_id: str,
    payload: dict[str, Any],
    now: datetime,
    working: Callable[[], None] | None = None,
) -> None:
    """Stream one answer into the cache, then write it down."""
    owner = _owner_for(db, payload)
    gate = FigureGate(
        allowed=frozenset(payload.get("figures", ())),
        quoted=frozenset(payload.get("quoted", ())),
        people_below=0 if payload.get("owner_id") else VISITOR_HEADCOUNT_BELOW,
    )
    choices = ChoiceGate()
    safe: list[str] = []
    announce = announcer(
        turn_id, gate=gate, payload=payload, safe=safe, working=working
    )
    desk = LookupDesk(db=db, owner=owner, now=now, gate=gate, announce=announce)
    try:
        with claude() as client:
            stream = _asked(client, payload=payload, desk=desk)
            drain(
                stream,
                turn_id=turn_id,
                gate=gate,
                choices=choices,
                payload=payload,
                safe=safe,
            )
    except LLMError as exc:
        _fail(db, turn_id, owner=owner, payload=payload, exc=exc)
        return
    except Exception:
        _broke(db, turn_id, payload=payload)
        raise
    _finish(
        db,
        turn_id,
        owner=owner,
        payload=payload,
        gate=gate,
        choices=choices,
        safe=safe,
        result=stream.result,
        now=now,
        changes=desk.changes,
    )


def _finish(
    db: Session,
    turn_id: str,
    *,
    owner: User,
    payload: dict[str, Any],
    gate: FigureGate,
    choices: ChoiceGate,
    safe: list[str],
    result: Any,
    now: datetime,
    changes: list[dict[str, Any]] = (),  # type: ignore[assignment]
) -> None:
    """The last frame, the ledger row, and the message on the thread."""
    from app.modules.audit.services import record_llm_result

    text = "".join(safe).rstrip()
    offered = [
        *picked(keys=choices.keys, offers=payload.get("offers", [])),
        *changes,
    ]
    replies = list(
        vetted_replies(choices.replies, allowed=gate.allowed, quoted=gate.quoted)
    )
    if result.truncated:
        text, replies = _cut_short(text, owner=owner, payload=payload)
    publish(
        turn_id,
        text,
        gate=gate,
        payload=payload,
        done=True,
        choices=offered,
        replies=replies,
    )
    record_llm_result(
        db,
        owner=owner,
        purpose=LLMPurpose.CHAT,
        result=result,
        masked=gate.masked,
        related_type=RELATED_TYPE,
        related_id=payload.get("message_id", ""),
    )
    _store(
        db,
        payload=payload,
        text=text,
        gate=gate,
        choices=[*offered, *reply_items(replies)],
        now=now,
    )


def _cut_short(
    text: str, *, owner: User, payload: dict[str, Any]
) -> tuple[str, list[str]]:
    """An answer that ran out of room, said to be one, with a way to the rest."""
    logger.warning(
        "chat answer cut at max_tokens",
        extra={
            "prompt_version": payload.get("prompt_version", ""),
            "max_tokens": payload.get("max_tokens", 0),
        },
    )
    note, carry_on = str(CUT_SHORT), str(CARRY_ON)
    return f"{text}…\n\n**{note}**", [carry_on]


def _asked(
    client: ClaudeClient, *, payload: dict[str, Any], desk: LookupDesk
) -> TextStream | ToolStream:
    """The question as Claude is asked it, with look-ups when the turn has them."""
    asked: dict[str, Any] = {
        "prompt": payload["question"],
        "system": payload.get("system", ""),
        "system_tail": payload.get("system_tail", ""),
        "history": tuple((role, text) for role, text in payload.get("history", ())),
        "prompt_name": PROMPT_NAME,
        "prompt_version": payload.get("prompt_version", ""),
        "max_tokens": int(payload.get("max_tokens", 0)),
    }
    if not payload.get("lookups"):
        return client.stream(**asked)
    return client.converse(**asked, tools=TOOLS, run_tool=desk, max_rounds=MAX_ROUNDS)


def _owner_for(db: Session, payload: dict[str, Any]) -> User:
    """Whose ledger this call lands on."""
    owner_id = payload.get("owner_id", "")
    if not owner_id:
        return public_chat_owner(db)
    try:
        found = db.get(User, uuid.UUID(str(owner_id)))
    except ValueError:
        found = None
    return found if found is not None else public_chat_owner(db)


def _fail(
    db: Session, turn_id: str, *, owner: User, payload: dict[str, Any], exc: LLMError
) -> None:
    """Say so on the screen, and write the row that explains the bill."""
    from app.modules.audit.services import record_llm_error

    logger.warning("chat answer failed: %s", exc)
    publish(
        turn_id,
        "",
        gate=FigureGate(allowed=frozenset()),
        payload=payload,
        done=True,
        error="failed",
    )
    record_llm_error(
        db,
        owner=owner,
        purpose=LLMPurpose.CHAT,
        exc=exc,
        prompt_name=PROMPT_NAME,
        prompt_version=payload.get("prompt_version", ""),
        model=model_for(ASKED),
        currency=str(settings.anthropic_price_currency),
        related_type=RELATED_TYPE,
        related_id=payload.get("message_id", ""),
    )
    _mark_failed(db, payload=payload)


def _message_key(payload: dict[str, Any]) -> uuid.UUID | None:
    raw = payload.get("message_id", "")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def _store(
    db: Session,
    *,
    payload: dict[str, Any],
    text: str,
    gate: FigureGate,
    choices: list[dict[str, str]],
    now: datetime,
) -> None:
    """Fill in the row that was created empty when the question arrived."""
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
            text=text,
            html=render(text),
            status=ChatMessageStatus.DONE,
            masked_figures=gate.masked,
            choices=choices,
            updated_at=now,
        )
    )
    db.execute(
        update(ChatSession)
        .where(ChatSession.id == session_id)
        .values(last_message_at=now)
    )


def _broke(db: Session, turn_id: str, *, payload: dict[str, Any]) -> None:
    """Close the turn on a failure that was not the model's."""
    logger.exception("chat answer broke")
    publish(
        turn_id,
        "",
        gate=FigureGate(allowed=frozenset()),
        payload=payload,
        done=True,
        error="failed",
    )
    _mark_failed(db, payload=payload)


def _mark_failed(db: Session, *, payload: dict[str, Any]) -> None:
    key = _message_key(payload)
    if key is not None:
        db.execute(
            update(ChatMessage)
            .where(ChatMessage.id == key)
            .values(status=ChatMessageStatus.FAILED)
        )


__all__ = ["SPENT", "LookupDesk", "answer_turn"]
