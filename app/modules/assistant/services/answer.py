"""Reading the model's answer, gating it, and publishing it as it is written.

The gates are the old chat's: ``core/chat/verify.py`` keeps an invented
figure off the screen and ``core/chat/choices.py`` splits the choice and
reply lines off. What is new is the desk - the account check, the search of
known fixes and the ticket - and the frame: the page is sent what was
written since the last frame (``delta``), and what can be pressed arrives
in its own field once the answer is finished.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from llmkit import ClaudeClient, LLMError, TextStream, ToolCall, ToolOutput, ToolStream
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.common.i18n import override
from app.common.llm import ASKED, claude, model_for
from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.assistant.constants import (
    GUEST_TICKET_KEY,
    GUEST_TICKET_TTL_SECONDS,
    LOOKING,
    OUT_KEY,
    PROMPT_NAME,
    RELATED_TYPE,
    STREAM_CHUNK_CHARS,
    TICKET_CHECKED_ITEMS,
    TICKET_SUMMARY_CHARS,
    TURN_TTL_SECONDS,
    ButtonKind,
    ButtonState,
    MessageStatus,
)
from app.modules.assistant.models import AssistantMessage, AssistantSession
from app.modules.audit.constants import LLMPurpose
from app.modules.chat.constants import LOOKING as LOOKUP_WORDS
from app.modules.chat.constants import LOOKING_DEFAULT, VISITOR_HEADCOUNT_BELOW
from app.modules.chat.copy import CARRY_ON, CUT_SHORT
from core.assistant.tools import (
    CHANGE_TOOL,
    HEALTH_TOOL,
    HELP_TOOL,
    MAX_TICKETS,
    NEW_TOOLS,
    TICKET_TOOL,
    TOOLS,
    with_reading,
)
from core.chat.choices import ChoiceGate, vetted_replies
from core.chat.lookups import MAX_CHANGES, MAX_LOOKUPS, MAX_ROUNDS
from core.chat.markdown import render
from core.chat.numbers import figures_in
from core.chat.verify import FigureGate

logger = logging.getLogger(__name__)

CHANGE_KEY = "P"
TICKET_KEY = "T"
PREPARING = "O'zgarishni tayyorlayapman…"
SPENT = "This answer has used all of its look-ups. Answer with what you already have."
STOPPED = "The person pressed stop. Do not look anything up; write nothing more."
NO_ACCOUNT = (
    "Not available: this person has no account here. Answer in words, and "
    "prepare a ticket if they need a person."
)
TICKET_PREPARED = (
    "Prepared. The person now sees a «Mutaxassisga yuborish» button under your "
    "answer; nothing has been sent and nothing will be until they press it. "
    "Say in one or two sentences what you found and that they can send it to "
    "a specialist with the button. Never say it was sent."
)
GUEST_TICKET_PREPARED = (
    "Prepared. Under your answer the product now asks this visitor for a name "
    "and a phone number; a specialist writes or calls back once they leave "
    "them. Say that in one sentence. Do not ask for the phone yourself."
)
# A visitor has no account to look into: only the two that need none.
VISITOR_TOOLS = tuple(
    tool for tool in NEW_TOOLS if tool.name in (HELP_TOOL, TICKET_TOOL)
)


@dataclass(slots=True)
class Halt:
    """The client's stop. ``text`` is what they were shown when it came;
    nothing after it is shown or kept."""

    turn_id: str
    shown: str = ""
    text: str | None = None

    @property
    def stopped(self) -> bool:
        return self.text is not None

    def check(self) -> bool:
        """Whether to stop here; the first time, keep what was shown."""
        from app.modules.assistant.services.threads import stop_asked

        if self.text is None and stop_asked(self.turn_id):
            self.text = self.shown.rstrip()
        return self.text is not None


@dataclass(slots=True)
class Desk:
    """One answer's look-ups: whose account, when, and the gate they widen."""

    db: Session
    owner: User | None
    now: datetime
    gate: FigureGate
    language: str = ""
    made: int = 0
    announce: Callable[[str], None] | None = None
    halt: Halt | None = None
    changes: list[dict[str, Any]] = field(default_factory=list)
    tickets: list[dict[str, Any]] = field(default_factory=list)
    _scope: PageScope | None = None
    _counted: PageScope | None = None

    def __call__(self, call: ToolCall) -> ToolOutput:
        self.made += 1
        if self.halt is not None and self.halt.stopped:
            return ToolOutput(text=STOPPED, is_error=True)
        if self.made > MAX_LOOKUPS:
            return ToolOutput(text=SPENT, is_error=True)
        if call.name == TICKET_TOOL:
            return self._ticket(call)
        self._say(call.name)
        if call.name == HELP_TOOL:
            return self._help(call)
        if self.owner is None:
            return ToolOutput(text=NO_ACCOUNT, is_error=True)
        self._scopes()
        if call.name == CHANGE_TOOL:
            return self._change(call)
        with override(self.owner.language or ""):
            text = self._read(call)
        self.gate.allow(figures_in(text))
        logger.info("assistant_lookup", extra={"lookup": call.name, "chars": len(text)})
        return ToolOutput(text=with_reading(call.name, text))

    def _say(self, name: str) -> None:
        if self.announce is not None:
            words = LOOKING.get(name) or LOOKUP_WORDS.get(name, LOOKING_DEFAULT)
            self.announce(PREPARING if name == CHANGE_TOOL else str(words))

    def _scopes(self) -> None:
        from app.modules.chat.selectors.scope import asked_scopes

        if self._scope is None:
            assert self.owner is not None
            self._scope, self._counted = asked_scopes(self.db, owner=self.owner)

    def _read(self, call: ToolCall) -> str:
        from app.modules.assistant.selectors.health import account_health
        from app.modules.chat.selectors.lookups import answer_lookup

        assert self.owner is not None and self._scope is not None
        if call.name == HEALTH_TOOL:
            return account_health(
                self.db, owner=self.owner, scope=self._scope, now=self.now
            )
        return answer_lookup(
            self.db,
            owner=self.owner,
            name=call.name,
            arguments=call.arguments,
            scope=self._scope,
            now=self.now,
            counted=self._counted,
        )

    def _help(self, call: ToolCall) -> ToolOutput:
        from app.modules.assistant.selectors.help import help_search

        text = help_search(
            self.db,
            query=str(getattr(call.arguments, "query", "")),
            language=self.language,
        )
        self.gate.allow(figures_in(text))
        return ToolOutput(text=with_reading(HELP_TOOL, text))

    def _change(self, call: ToolCall) -> ToolOutput:
        """A change the owner asked for, checked and described by the old
        chat's own service; never carried out here."""
        from app.modules.chat.services.changes import prepare_change

        if len(self.changes) >= MAX_CHANGES:
            return ToolOutput(
                text="This answer already prepared as many changes as one answer may.",
                is_error=True,
            )
        assert self.owner is not None and self._scope is not None
        prepared = prepare_change(
            self.db,
            owner=self.owner,
            arguments=call.arguments,
            scope=self._scope,
            key=f"{CHANGE_KEY}{len(self.changes) + 1}",
        )
        if prepared.item is not None:
            self.changes.append(prepared.item)
        self.gate.allow(figures_in(prepared.text))
        return ToolOutput(text=prepared.text, is_error=prepared.item is None)

    def _ticket(self, call: ToolCall) -> ToolOutput:
        """A request for a person: a button, and nothing sent."""
        if len(self.tickets) >= MAX_TICKETS:
            return ToolOutput(
                text="A ticket is already prepared for this answer.", is_error=True
            )
        self._say(TICKET_TOOL)
        summary = " ".join(str(getattr(call.arguments, "summary", "")).split())
        checked = [
            " ".join(str(line).split())
            for line in getattr(call.arguments, "checked", ())
            if str(line).strip()
        ][:TICKET_CHECKED_ITEMS]
        guest = self.owner is None
        self.tickets.append(
            {
                "kind": ButtonKind.GUEST_TICKET if guest else ButtonKind.TICKET,
                "key": f"{TICKET_KEY}{len(self.tickets) + 1}",
                "label": "Mutaxassisga yuborish",
                "state": ButtonState.OPEN,
                "summary": summary[:TICKET_SUMMARY_CHARS],
                "checked": checked,
            }
        )
        return ToolOutput(text=GUEST_TICKET_PREPARED if guest else TICKET_PREPARED)


def answer_turn(
    db: Session,
    *,
    turn_id: str,
    payload: dict[str, Any],
    now: datetime,
    working: Callable[[], None] | None = None,
) -> None:
    """Stream one answer into the cache, then write it down."""
    from app.modules.chat.services.quota import public_chat_owner

    owner = _owner(db, payload)
    gate = FigureGate(
        allowed=frozenset(payload.get("figures", ())),
        quoted=frozenset(payload.get("quoted", ())),
        people_below=0 if owner is not None else VISITOR_HEADCOUNT_BELOW,
    )
    choices = ChoiceGate()
    safe: list[str] = []
    halt = Halt(turn_id)
    if halt.check():
        _stopped_early(db, turn_id, payload=payload, now=now)
        return

    def announce(words: str) -> None:
        if halt.check():
            _show_stopped(turn_id, payload=payload, halt=halt, masked=gate.masked)
            return
        halt.shown = "".join(safe)
        publish(turn_id, halt.shown, payload=payload, masked=gate.masked, status=words)
        if working is not None:
            working()

    desk = Desk(
        db=db,
        owner=owner,
        now=now,
        gate=gate,
        language=str(payload.get("language", "")),
        announce=announce,
        halt=halt,
    )
    try:
        with claude(cached=True) as client:
            stream = _asked(client, payload=payload, desk=desk)
            _drain(
                stream,
                turn_id=turn_id,
                gate=gate,
                choices=choices,
                payload=payload,
                safe=safe,
                halt=halt,
            )
    except LLMError as exc:
        _fail(
            db, turn_id, owner=owner or public_chat_owner(db), payload=payload, exc=exc
        )
        return
    except Exception:
        logger.exception("assistant answer broke")
        publish(turn_id, "", payload=payload, done=True, error="failed")
        _mark_failed(db, payload=payload)
        raise
    _finish(
        db,
        turn_id,
        owner=owner or public_chat_owner(db),
        payload=payload,
        gate=gate,
        choices=choices,
        text="".join(safe).rstrip(),
        result=stream.result,
        now=now,
        desk=desk,
        halt=halt,
    )


def _show_stopped(
    turn_id: str, *, payload: dict[str, Any], halt: Halt, masked: int
) -> None:
    """The last frame, at once: the page stops waiting while the model is
    read out behind it, so the ledger still knows what it cost."""
    publish(
        turn_id,
        halt.text or "",
        payload=payload,
        masked=masked,
        done=True,
        stopped=True,
    )


def _stopped_early(
    db: Session, turn_id: str, *, payload: dict[str, Any], now: datetime
) -> None:
    """Stopped before the model was asked: nothing written, nothing spent,
    and the question is not counted."""
    publish(turn_id, "", payload=payload, done=True, stopped=True)
    _store(
        db,
        payload=payload,
        text="",
        gate=None,
        buttons=[],
        replies=[],
        now=now,
        stopped=True,
    )


def publish(
    turn_id: str,
    text: str,
    *,
    payload: dict[str, Any],
    masked: int = 0,
    done: bool = False,
    error: str = "",
    status: str = "",
    buttons: list[dict[str, Any]] | None = None,
    replies: list[str] | None = None,
    stopped: bool = False,
) -> None:
    """The answer so far, as the stream's door reads it. ``html`` is drawn
    once, with the last frame: the page writes ``delta`` as it arrives."""
    cache.set(
        OUT_KEY.format(turn_id=turn_id),
        {
            "text": text,
            "html": render(text) if done else "",
            "done": done,
            "error": error,
            "masked": masked,
            "status": status,
            "owner_id": payload.get("owner_id", ""),
            "message_id": payload.get("message_id", ""),
            "session_id": payload.get("session_id", ""),
            "buttons": buttons or [],
            "replies": replies or [],
            "stopped": stopped,
        },
        TURN_TTL_SECONDS,
    )


def _asked(
    client: ClaudeClient, *, payload: dict[str, Any], desk: Desk
) -> TextStream | ToolStream:
    """The question as the model is asked it. The base is the cached system
    prompt; the question's own sections and the Context follow it."""
    return client.converse(
        prompt=payload["question"],
        system=payload.get("system", ""),
        system_tail=payload.get("system_tail", ""),
        history=tuple((role, text) for role, text in payload.get("history", ())),
        prompt_name=PROMPT_NAME,
        prompt_version=payload.get("prompt_version", ""),
        max_tokens=int(payload.get("max_tokens", 0)),
        tools=TOOLS if desk.owner is not None else VISITOR_TOOLS,
        run_tool=desk,
        max_rounds=MAX_ROUNDS,
    )


def _drain(
    stream: TextStream | ToolStream,
    *,
    turn_id: str,
    gate: FigureGate,
    choices: ChoiceGate,
    payload: dict[str, Any],
    safe: list[str],
    halt: Halt,
) -> None:
    """Read the model's output into ``safe``, publishing as it fills. After
    a stop the rest is read and dropped: what it cost is still recorded."""
    pending = 0
    for piece in stream:
        if halt.stopped:
            continue
        safe.append(gate.feed(choices.feed(piece)))
        pending += len(piece)
        if pending >= STREAM_CHUNK_CHARS:
            if halt.check():
                _show_stopped(turn_id, payload=payload, halt=halt, masked=gate.masked)
                continue
            halt.shown = "".join(safe)
            publish(turn_id, halt.shown, payload=payload, masked=gate.masked)
            pending = 0
    if halt.stopped:
        return
    safe.append(gate.feed(choices.flush()))
    safe.append(gate.flush())


def _finish(
    db: Session,
    turn_id: str,
    *,
    owner: User,
    payload: dict[str, Any],
    gate: FigureGate,
    choices: ChoiceGate,
    text: str,
    result: Any,
    now: datetime,
    desk: Desk,
    halt: Halt,
) -> None:
    """The last frame, the ledger row, and the message on the thread."""
    from app.modules.audit.services import record_llm_result
    from app.modules.chat.selectors.choices import picked

    if halt.stopped:
        _show_stopped(turn_id, payload=payload, halt=halt, masked=gate.masked)
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
            text=halt.text or "",
            gate=gate,
            buttons=[],
            replies=[],
            now=now,
            stopped=True,
        )
        return

    offers = [
        {**item, "kind": ButtonKind.OFFER, "state": ButtonState.OPEN}
        for item in picked(keys=choices.keys, offers=payload.get("offers", []))
    ]
    buttons = [*desk.tickets, *offers, *desk.changes]
    replies = list(
        vetted_replies(choices.replies, allowed=gate.allowed, quoted=gate.quoted)
    )
    if result.truncated:
        logger.warning(
            "assistant answer cut at max_tokens",
            extra={"prompt_version": payload.get("prompt_version", "")},
        )
        text, replies = f"{text}…\n\n**{CUT_SHORT}**", [str(CARRY_ON)]
    if desk.tickets and desk.owner is None:
        _keep_for_guest(turn_id, payload=payload, ticket=desk.tickets[0], answer=text)
    publish(
        turn_id,
        text,
        payload=payload,
        masked=gate.masked,
        done=True,
        buttons=buttons,
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
        buttons=buttons,
        replies=replies,
        now=now,
    )


def _keep_for_guest(
    turn_id: str, *, payload: dict[str, Any], ticket: dict[str, Any], answer: str
) -> None:
    """A visitor's request waits for their name and phone."""
    try:
        cache.set(
            GUEST_TICKET_KEY.format(turn_id=turn_id),
            {
                "question": payload.get("question", ""),
                "summary": ticket.get("summary", ""),
                "checked": ticket.get("checked", []),
                "answer": answer,
            },
            GUEST_TICKET_TTL_SECONDS,
        )
    except Exception:
        logger.exception("assistant guest ticket not kept")


def _owner(db: Session, payload: dict[str, Any]) -> User | None:
    """The subscriber this turn belongs to, or nothing for a visitor."""
    key = _uuid(payload.get("owner_id", ""))
    return db.get(User, key) if key is not None else None


def _uuid(raw: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw)) if raw else None
    except ValueError:
        return None


def _store(
    db: Session,
    *,
    payload: dict[str, Any],
    text: str,
    gate: FigureGate | None,
    buttons: list[dict[str, Any]],
    replies: list[str],
    now: datetime,
    stopped: bool = False,
) -> None:
    """Fill in the row that was created empty when the question arrived."""
    key = _uuid(payload.get("message_id", ""))
    if key is None:
        return
    found = db.execute(
        select(AssistantMessage.session_id, AssistantMessage.meta).where(
            AssistantMessage.id == key
        )
    ).first()
    if found is None:
        return
    session_id, meta = found
    db.execute(
        update(AssistantMessage)
        .where(AssistantMessage.id == key)
        .values(
            text=text,
            html=render(text),
            status=MessageStatus.DONE,
            masked_figures=gate.masked if gate is not None else 0,
            buttons=buttons,
            replies=replies,
            meta={**(meta or {}), "stopped": True} if stopped else (meta or {}),
            updated_at=now,
        )
    )
    db.execute(
        update(AssistantSession)
        .where(AssistantSession.id == session_id)
        .values(last_message_at=now)
    )


def _fail(
    db: Session, turn_id: str, *, owner: User, payload: dict[str, Any], exc: LLMError
) -> None:
    """Say so on the screen, and write the row that explains the bill."""
    from app.modules.audit.services import record_llm_error

    logger.warning("assistant answer failed: %s", exc)
    publish(turn_id, "", payload=payload, done=True, error="failed")
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


def _mark_failed(db: Session, *, payload: dict[str, Any]) -> None:
    key = _uuid(payload.get("message_id", ""))
    if key is not None:
        db.execute(
            update(AssistantMessage)
            .where(AssistantMessage.id == key)
            .values(status=MessageStatus.FAILED)
        )


__all__ = ["Desk", "answer_turn", "publish"]
