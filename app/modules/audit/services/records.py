"""LLM calls, errors and stuck changes: the audit trail beyond the outbox."""

import hashlib
import logging
import secrets
import traceback
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any

from llmkit import (
    MICROS_PER_MINOR,
    ClaudeRateLimited,
    ClaudeRefused,
    LLMError,
    LLMResult,
    Spend,
    StructuredOutputError,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.env import BASE_DIR
from app.modules.accounts.models import User
from app.modules.audit.constants import (
    ERROR_REFERENCE_ALPHABET,
    ERROR_REFERENCE_LENGTH,
    ERROR_RETENTION_DAYS,
    ERROR_TRACE_CHARS,
    UNRESOLVED_AFTER_MINUTES,
    UNRESOLVED_REPORT_ACTIONS,
    UNRESOLVED_REPORT_HOURS,
    ActionStatus,
    ActionType,
    LLMCallStatus,
    LLMPurpose,
)
from app.modules.audit.models import ActionLog, ErrorEvent, LLMCall

logger = logging.getLogger(__name__)
REFERENCE_TRIES = 3
WATCHED = (
    ActionType.TARGETING_SWAP,
    ActionType.CREATE_AUDIENCE,
    ActionType.FILL_AUDIENCE,
    ActionType.DELETE_AUDIENCE,
    ActionType.FORGET_MEMBERS,
)


def record_llm_result(
    db: Session,
    *,
    owner: User,
    purpose: LLMPurpose,
    result: LLMResult[Any],
    related_type: str = "",
    related_id: str | uuid.UUID = "",
    masked: int = 0,
    workspace: str = "",
) -> LLMCall:
    call = LLMCall(
        owner_id=owner.id,
        purpose=purpose,
        prompt_name=result.prompt_name,
        prompt_version=result.prompt_version,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cache_write_tokens=result.cache_write_tokens,
        cache_read_tokens=result.cache_read_tokens,
        truncated=result.truncated,
        cost_micros=result.cost_micros,
        cost_minor=result.cost_minor,
        currency=result.currency,
        latency_ms=result.latency_ms,
        attempts=result.attempts,
        rounds=result.rounds,
        tool_calls=result.tool_calls,
        masked_figures=masked,
        workspace=workspace,
        status=LLMCallStatus.OK,
        related_type=related_type,
        related_id=str(related_id),
    )
    db.add(call)
    db.flush()
    return call


def record_llm_failure(
    db: Session,
    *,
    owner: User,
    purpose: LLMPurpose,
    status: LLMCallStatus,
    prompt_name: str,
    prompt_version: str,
    model: str,
    currency: str,
    attempts: int = 1,
    spent: Spend | None = None,
    related_type: str = "",
    related_id: str | uuid.UUID = "",
    workspace: str = "",
) -> LLMCall:
    spent = spent or Spend()
    call = LLMCall(
        owner_id=owner.id,
        purpose=purpose,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        model=model,
        currency=currency,
        attempts=attempts,
        input_tokens=spent.input_tokens,
        output_tokens=spent.output_tokens,
        cache_write_tokens=spent.cache_write_tokens,
        cache_read_tokens=spent.cache_read_tokens,
        cost_micros=spent.cost_micros,
        cost_minor=spent.cost_minor,
        latency_ms=0,
        truncated=0,
        rounds=0,
        tool_calls=0,
        masked_figures=0,
        workspace=workspace,
        status=status,
        related_type=related_type,
        related_id=str(related_id),
    )
    db.add(call)
    db.flush()
    return call


def record_llm_error(
    db: Session,
    *,
    owner: User,
    purpose: LLMPurpose,
    exc: LLMError,
    prompt_name: str,
    prompt_version: str,
    model: str,
    currency: str,
    related_type: str = "",
    related_id: str | uuid.UUID = "",
    workspace: str = "",
) -> LLMCall:
    if isinstance(exc, ClaudeRateLimited):
        status = LLMCallStatus.RATE_LIMITED
    elif isinstance(exc, StructuredOutputError):
        status = LLMCallStatus.SCHEMA_ERROR
    else:
        status = LLMCallStatus.FAILED
    attempts = (
        (exc.attempts or 1)
        if isinstance(exc, StructuredOutputError | ClaudeRefused)
        else 1
    )
    return record_llm_failure(
        db,
        owner=owner,
        purpose=purpose,
        status=status,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        model=model,
        currency=currency,
        attempts=attempts,
        spent=exc.spent,
        related_type=related_type,
        related_id=related_id,
        workspace=workspace,
    )


def backfill_cost_micros(db: Session, *, batch: int) -> int:
    ids = list(
        db.scalars(
            select(LLMCall.id)
            .where(LLMCall.cost_micros == 0, LLMCall.cost_minor > 0)
            .order_by(LLMCall.id)
            .limit(batch)
        )
    )
    if not ids:
        return 0
    done = db.execute(
        update(LLMCall)
        .where(LLMCall.id.in_(ids), LLMCall.cost_micros == 0)
        .values(cost_micros=LLMCall.cost_minor * MICROS_PER_MINOR)
    ).rowcount
    db.commit()
    return int(done)


def purge_errors(db: Session, *, now: datetime) -> int:
    removed = db.execute(
        delete(ErrorEvent).where(
            ErrorEvent.last_seen_at < now - timedelta(days=ERROR_RETENTION_DAYS)
        )
    ).rowcount
    db.commit()
    if removed:
        logger.info("errors purged", extra={"rows": removed})
    return int(removed)


def record_error(
    db: Session,
    *,
    owner: User,
    exc: BaseException,
    where: str,
    now: datetime,
    path: str = "",
    method: str = "",
) -> str:
    try:
        return _record(
            db, owner=owner, exc=exc, where=where, now=now, path=path, method=method
        )
    except Exception:
        logger.exception("an error could not be recorded")
        return ""


def _record(
    db: Session,
    *,
    owner: User,
    exc: BaseException,
    where: str,
    now: datetime,
    path: str,
    method: str,
) -> str:
    mark = _fingerprint(exc=exc, where=where)
    open_one = db.scalar(
        select(ErrorEvent).where(
            ErrorEvent.owner_id == owner.id,
            ErrorEvent.fingerprint == mark,
            ErrorEvent.resolved_at.is_(None),
        )
    )
    if open_one is not None:
        db.execute(
            update(ErrorEvent)
            .where(ErrorEvent.id == open_one.id)
            .values(seen=ErrorEvent.seen + 1, last_seen_at=now, updated_at=now)
        )
        db.commit()
        return open_one.reference
    for _ in range(REFERENCE_TRIES):
        row = ErrorEvent(
            owner_id=owner.id,
            fingerprint=mark,
            exception=type(exc).__name__[:200],
            message=str(exc)[:2000],
            where=where[:300],
            path=path[:500],
            method=method[:8],
            trace="".join(traceback.format_exception(exc))[-ERROR_TRACE_CHARS:],
            seen=1,
            last_seen_at=now,
            reference="".join(
                secrets.choice(ERROR_REFERENCE_ALPHABET)
                for _ in range(ERROR_REFERENCE_LENGTH)
            ),
        )
        try:
            with db.begin_nested():
                db.add(row)
            db.commit()
        except IntegrityError:
            raced = db.scalar(
                select(ErrorEvent).where(
                    ErrorEvent.owner_id == owner.id,
                    ErrorEvent.fingerprint == mark,
                    ErrorEvent.resolved_at.is_(None),
                )
            )
            if raced is not None:
                return raced.reference
            continue
        return row.reference
    logger.error("a reference could not be drawn", extra={"tries": REFERENCE_TRIES})
    return ""


def _fingerprint(*, exc: BaseException, where: str) -> str:
    frame = _ours(exc.__traceback__)
    place = f"{frame[0]}:{frame[1]}" if frame else where
    seed = f"{type(exc).__module__}.{type(exc).__name__}|{place}"
    return hashlib.sha256(seed.encode()).hexdigest()[:64]


def _ours(tb: TracebackType | None) -> tuple[str, str] | None:
    root = str(BASE_DIR)
    for frame in reversed(traceback.extract_tb(tb)):
        name = str(frame.filename)
        if name.startswith(root) and "site-packages" not in name:
            return str(Path(name).relative_to(root)), frame.name
    return None


def settle_error(db: Session, *, event_id: str, by: User, now: datetime) -> bool:
    closed = db.execute(
        update(ErrorEvent)
        .where(
            ErrorEvent.id == uuid.UUID(str(event_id)), ErrorEvent.resolved_at.is_(None)
        )
        .values(resolved_at=now, resolved_by_id=by.id, updated_at=now)
    ).rowcount
    db.commit()
    return bool(closed)


def report_unresolved_actions(db: Session, *, now: datetime) -> int:
    rows = db.execute(
        select(
            ActionLog.action,
            func.count(ActionLog.id).label("stuck"),
            func.min(ActionLog.created_at).label("oldest"),
        )
        .where(
            ActionLog.status == ActionStatus.PENDING,
            ActionLog.action.in_(WATCHED),
            ActionLog.created_at >= now - timedelta(hours=UNRESOLVED_REPORT_HOURS),
            ActionLog.created_at <= now - timedelta(minutes=UNRESOLVED_AFTER_MINUTES),
        )
        .group_by(ActionLog.action)
        .order_by(func.count(ActionLog.id).desc())
    ).all()
    if not rows:
        return 0
    total = sum(row.stuck for row in rows)
    logger.error(
        "changes were begun and never resolved",
        extra={
            "changes": total,
            "minutes": UNRESOLVED_AFTER_MINUTES,
            "actions": [
                {
                    "action": row.action,
                    "stuck": row.stuck,
                    "oldest": row.oldest.isoformat(),
                }
                for row in rows[:UNRESOLVED_REPORT_ACTIONS]
            ],
        },
    )
    return total
