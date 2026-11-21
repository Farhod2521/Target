"""Answering one office question: look-ups, the streamed words, the row.

The model reads the office's figures through :class:`Desk` and writes; the
words pass :class:`core.chat.verify.FigureGate` on the way to the screen, so
a figure no look-up returned is shown as ``[?]``. The answer so far is kept
in the cache under the turn, where the stream's door reads it.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from llmkit import ToolCall, ToolOutput
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.common.dates import localtime
from app.common.llm import ASKED, claude, model_for
from app.modules.accounts.models import User
from app.modules.audit.constants import LLMPurpose
from app.modules.officeai.constants import (
    LOOKING_DEFAULT,
    MAX_LOOKUPS,
    MAX_ROUNDS,
    ORDINALS_BELOW,
    OUT_KEY,
    PROMPT_NAME,
    RELATED_TYPE,
    STOP_KEY,
    STREAM_CHUNK_CHARS,
    TURN_TTL_SECONDS,
    MessageStatus,
)
from app.modules.officeai.models import OfficeAiMessage, OfficeAiThread
from app.modules.officeai.selectors import facts, statistics
from core.chat.markdown import render
from core.chat.numbers import figures_in
from core.chat.verify import FigureGate, dates_in
from core.officeai.tools import (
    CUSTOMER_LIST,
    CUSTOMERS,
    LOOKING,
    MONEY,
    MONEY_TOOLS,
    PAYMENTS,
    PLANS,
    PLATFORM,
    QUEUES,
    SALES,
    STATS,
    tools_for,
)

logger = logging.getLogger(__name__)

SPENT = "This answer has used all of its look-ups. Answer with what you have."
NO_MONEY = (
    "Not available: this person does not see money. Say that money is shown "
    "to Finance and the Owner, and answer the rest."
)
FAILED_MODEL = "model"
FAILED_BROKE = "broke"
FAILED_STUCK = "stuck"
STOPPED = "The person pressed stop. Do not look anything up; write nothing more."


def stop(*, turn_id: str, viewer: str) -> bool:
    """Ask the answer being written to end where it is. False when there is
    nothing to stop, or it is someone else's."""
    from app.modules.officeai.constants import TURN_KEY

    state = cache.get(OUT_KEY.format(turn_id=turn_id))
    if isinstance(state, dict):
        if state.get("staff_id") != viewer or state.get("done"):
            return False
    else:
        payload = cache.get(TURN_KEY.format(turn_id=turn_id))
        if not isinstance(payload, dict) or payload.get("staff_id") != viewer:
            return False
    cache.set(STOP_KEY.format(turn_id=turn_id), True, TURN_TTL_SECONDS)
    return True


def _stop_asked(turn_id: str) -> bool:
    try:
        return bool(cache.get(STOP_KEY.format(turn_id=turn_id)))
    except Exception:
        return False


@dataclass(slots=True)
class Halt:
    """The person's stop. ``text`` is what was shown when it came."""

    turn_id: str
    shown: str = ""
    text: str | None = None

    @property
    def stopped(self) -> bool:
        return self.text is not None

    def check(self) -> bool:
        if self.text is None and _stop_asked(self.turn_id):
            self.text = self.shown.rstrip()
        return self.text is not None


@dataclass(slots=True)
class Desk:
    """One answer's look-ups, and the gate the figures they return open."""

    db: Session
    staff: User
    now: datetime
    sees_money: bool
    gate: FigureGate
    halt: Halt
    announce: Callable[[str], None] | None = None
    made: int = 0
    used: list[str] = field(default_factory=list)

    def __call__(self, call: ToolCall) -> ToolOutput:
        self.made += 1
        if self.halt.stopped:
            return ToolOutput(text=STOPPED, is_error=True)
        if self.made > MAX_LOOKUPS:
            return ToolOutput(text=SPENT, is_error=True)
        if call.name in MONEY_TOOLS and not self.sees_money:
            return ToolOutput(text=NO_MONEY, is_error=True)
        if self.announce is not None:
            self.announce(LOOKING.get(call.name, LOOKING_DEFAULT))
        text = self._read(call)
        self.gate.allow(figures_in(text))
        self.gate.allow_dates(dates_in(text))
        self.used.append(call.name)
        logger.info("office_ai_lookup", extra={"lookup": call.name, "chars": len(text)})
        return ToolOutput(text=text)

    def _read(self, call: ToolCall) -> str:
        db, now, arguments = self.db, self.now, call.arguments
        if call.name == CUSTOMERS:
            return facts.customers_summary(db, span=arguments, now=now)
        if call.name == MONEY:
            return facts.money_summary(db, span=arguments, now=now)
        if call.name == PLATFORM:
            return facts.platform_activity(
                db,
                span=arguments,
                now=now,
                sees_money=self.sees_money,
            )
        if call.name == QUEUES:
            return facts.waiting_now(db, query=arguments, now=now)
        if call.name == SALES:
            return facts.sales_by_manager(db, span=arguments, now=now)
        if call.name == PAYMENTS:
            return facts.latest_payments(db)
        if call.name == CUSTOMER_LIST:
            return facts.customer_list(db, query=arguments, now=now)
        if call.name == PLANS:
            return facts.plans_summary(db, now=now)
        if call.name == STATS:
            return statistics.statistics(db, query=arguments, now=now)
        return f"There is no look-up called {call.name}."


def publish(
    turn_id: str,
    text: str,
    *,
    payload: dict[str, Any],
    masked: int = 0,
    done: bool = False,
    error: str = "",
    status: str = "",
    stopped: bool = False,
    lookups: list[str] | None = None,
) -> None:
    """The answer so far, as the stream's door reads it."""
    cache.set(
        OUT_KEY.format(turn_id=turn_id),
        {
            "text": text,
            "html": render(text) if done else "",
            "done": done,
            "error": error,
            "masked": masked,
            "status": status,
            "stopped": stopped,
            "lookups": list(lookups or ()),
            "staff_id": payload.get("staff_id", ""),
            "message_id": payload.get("message_id", ""),
            "thread_id": payload.get("thread_id", ""),
        },
        TURN_TTL_SECONDS,
    )


def answer_turn(
    db: Session,
    *,
    turn_id: str,
    payload: dict[str, Any],
    now: datetime,
) -> None:
    """Stream one answer into the cache, then write it down."""
    from llmkit import LLMError

    staff = _staff(db, payload)
    if staff is None:
        return
    sees_money = bool(payload.get("sees_money"))
    # Today is in the prompt's Context, so it may be said back; a list of
    # rows may be numbered.
    today = f"{localtime(now):%d.%m.%Y}"
    gate = FigureGate(
        allowed=figures_in(today),
        quoted=frozenset(payload.get("quoted", ())),
        people_below=0,
        ordinals_below=ORDINALS_BELOW,
        dates=dates_in(today),
    )
    safe: list[str] = []
    halt = Halt(turn_id)
    if halt.check():
        publish(turn_id, "", payload=payload, done=True, stopped=True)
        _store(db, payload=payload, text="", masked=0, meta={"stopped": True}, now=now)
        return

    def announce(words: str) -> None:
        if halt.check():
            _show_stopped(turn_id, payload=payload, halt=halt, masked=gate.masked)
            return
        halt.shown = "".join(safe)
        publish(turn_id, halt.shown, payload=payload, masked=gate.masked, status=words)

    desk = Desk(
        db=db,
        staff=staff,
        now=now,
        sees_money=sees_money,
        gate=gate,
        halt=halt,
        announce=announce,
    )
    try:
        with claude(cached=True) as client:
            stream = client.converse(
                prompt=payload["question"],
                system=payload.get("system", ""),
                system_tail=payload.get("system_tail", ""),
                history=tuple(
                    (role, text) for role, text in payload.get("history", ())
                ),
                prompt_name=PROMPT_NAME,
                prompt_version=payload.get("prompt_version", ""),
                max_tokens=int(payload.get("max_tokens", 0)),
                tools=tools_for(sees_money=sees_money),
                run_tool=desk,
                max_rounds=MAX_ROUNDS,
            )
            pending = 0
            for piece in stream:
                if halt.stopped:
                    continue
                safe.append(gate.feed(piece))
                pending += len(piece)
                if pending >= STREAM_CHUNK_CHARS:
                    if halt.check():
                        _show_stopped(
                            turn_id, payload=payload, halt=halt, masked=gate.masked
                        )
                        continue
                    halt.shown = "".join(safe)
                    publish(turn_id, halt.shown, payload=payload, masked=gate.masked)
                    pending = 0
            if not halt.stopped:
                safe.append(gate.flush())
    except LLMError as exc:
        _fail(db, turn_id, staff=staff, payload=payload, exc=exc)
        return
    except Exception:
        logger.exception("office ai answer broke")
        publish(turn_id, "", payload=payload, done=True, error="failed")
        _mark_failed(db, payload=payload, reason=FAILED_BROKE)
        raise
    _finish(
        db,
        turn_id,
        staff=staff,
        payload=payload,
        text=halt.text if halt.stopped else "".join(safe).rstrip(),
        masked=gate.masked,
        result=stream.result,
        used=desk.used,
        stopped=halt.stopped,
        now=now,
    )


def _show_stopped(
    turn_id: str, *, payload: dict[str, Any], halt: Halt, masked: int
) -> None:
    publish(
        turn_id,
        halt.text or "",
        payload=payload,
        masked=masked,
        done=True,
        stopped=True,
    )


def _finish(
    db: Session,
    turn_id: str,
    *,
    staff: User,
    payload: dict[str, Any],
    text: str | None,
    masked: int,
    result: Any,
    used: list[str],
    stopped: bool,
    now: datetime,
) -> None:
    from app.modules.audit.services import record_llm_result

    words = text or ""
    publish(
        turn_id,
        words,
        payload=payload,
        masked=masked,
        done=True,
        stopped=stopped,
        lookups=used,
    )
    record_llm_result(
        db,
        owner=staff,
        purpose=LLMPurpose.OFFICE,
        result=result,
        masked=masked,
        related_type=RELATED_TYPE,
        related_id=payload.get("message_id", ""),
    )
    meta: dict[str, Any] = {"lookups": used}
    if stopped:
        meta["stopped"] = True
    _store(db, payload=payload, text=words, masked=masked, meta=meta, now=now)


def _fail(
    db: Session, turn_id: str, *, staff: User, payload: dict[str, Any], exc: Any
) -> None:
    from app.modules.audit.services import record_llm_error

    logger.warning("office ai answer failed: %s", exc)
    publish(turn_id, "", payload=payload, done=True, error="failed")
    record_llm_error(
        db,
        owner=staff,
        purpose=LLMPurpose.OFFICE,
        exc=exc,
        prompt_name=PROMPT_NAME,
        prompt_version=payload.get("prompt_version", ""),
        model=model_for(ASKED),
        currency=str(settings.anthropic_price_currency),
        related_type=RELATED_TYPE,
        related_id=payload.get("message_id", ""),
    )
    _mark_failed(db, payload=payload)


def _uuid(raw: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw)) if raw else None
    except ValueError:
        return None


def _staff(db: Session, payload: dict[str, Any]) -> User | None:
    key = _uuid(payload.get("staff_id", ""))
    return db.get(User, key) if key is not None else None


def _store(
    db: Session,
    *,
    payload: dict[str, Any],
    text: str,
    masked: int,
    meta: dict[str, Any],
    now: datetime,
) -> None:
    """Fill in the answer's row, created empty with the question."""
    key = _uuid(payload.get("message_id", ""))
    thread_id = _uuid(payload.get("thread_id", ""))
    if key is None:
        return
    db.execute(
        update(OfficeAiMessage)
        .where(OfficeAiMessage.id == key)
        .values(
            text=text,
            html=render(text),
            status=MessageStatus.DONE,
            masked_figures=masked,
            meta=meta,
            updated_at=now,
        )
    )
    if thread_id is not None:
        db.execute(
            update(OfficeAiThread)
            .where(OfficeAiThread.id == thread_id)
            .values(last_message_at=now)
        )


def _mark_failed(
    db: Session, *, payload: dict[str, Any], reason: str = FAILED_MODEL
) -> None:
    """``meta.error`` says why: ``model`` (Claude refused or was not
    reached), ``broke`` (our side), ``stuck`` (the worker never finished)."""
    key = _uuid(payload.get("message_id", ""))
    if key is not None:
        db.execute(
            update(OfficeAiMessage)
            .where(OfficeAiMessage.id == key)
            .values(status=MessageStatus.FAILED, meta={"error": reason})
        )


__all__ = ["Desk", "answer_turn", "publish", "stop"]
