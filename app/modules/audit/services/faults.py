"""Our own faults on a client's launch or press, kept for the Developers.

One row per client and fault while it is open; the same fault again counts
on it and keeps the latest context. Each new or repeated fault fires
``FAULT_HOOK`` after the commit, so the staff bot can tell the Developers.
Never raises: a fault that cannot be kept is logged and left.
"""

import hashlib
import json
import logging
import secrets
import traceback
import uuid
from datetime import datetime
from typing import Any, Final

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common import hooks
from app.common.db import utcnow
from app.modules.audit.constants import (
    ERROR_REFERENCE_ALPHABET,
    ERROR_REFERENCE_LENGTH,
    ERROR_TRACE_CHARS,
)
from app.modules.audit.models import ErrorEvent
from app.modules.audit.services.records import REFERENCE_TRIES, _ours

logger = logging.getLogger(__name__)
FAULT_HOOK: Final = "audit.fault"
# Fired after a fault is settled on the Developer page: db, path, by_id, now.
SETTLED_HOOK: Final = "audit.fault_settled"
# The key a launch's error_detail and a press's result_payload keep the
# fault's reference under.
FAULT_KEY: Final = "fault"
MESSAGE_CHARS: Final = 2000


def report_fault(
    db: Session,
    *,
    owner_id: uuid.UUID,
    code: str,
    message: str,
    where: str,
    subject: str,
    context: dict[str, Any] | None = None,
    exc: BaseException | None = None,
    now: datetime | None = None,
) -> str:
    """Keep the fault; returns its reference, or "" when it could not be kept.
    ``where``: the place in our code; ``subject``: what it was about
    (``launch:<id>``, ``action:<id>``). Commits."""
    try:
        return _report(
            db,
            owner_id=owner_id,
            code=code,
            message=message,
            where=where,
            subject=subject,
            context=context or {},
            exc=exc,
            now=now or utcnow(),
        )
    except Exception:
        db.rollback()
        logger.exception("a fault could not be kept", extra={"subject": subject})
        return ""


def _report(
    db: Session,
    *,
    owner_id: uuid.UUID,
    code: str,
    message: str,
    where: str,
    subject: str,
    context: dict[str, Any],
    exc: BaseException | None,
    now: datetime,
) -> str:
    mark = _fingerprint(code=code, where=where, exc=exc)
    kept = _plain({**context, "code": code})
    said = f"[{code}] {message}".strip()[:MESSAGE_CHARS]
    trace = "".join(traceback.format_exception(exc))[-ERROR_TRACE_CHARS:] if exc else ""
    open_one = _open(db, owner_id=owner_id, mark=mark)
    if open_one is not None:
        db.execute(
            update(ErrorEvent)
            .where(ErrorEvent.id == open_one.id)
            .values(
                seen=ErrorEvent.seen + 1,
                last_seen_at=now,
                updated_at=now,
                message=said,
                path=subject[:500],
                context=kept,
                **({"trace": trace} if trace else {}),
            )
        )
        db.commit()
        _tell(open_one.id)
        return open_one.reference
    for _ in range(REFERENCE_TRIES):
        row = ErrorEvent(
            owner_id=owner_id,
            fingerprint=mark,
            exception=(type(exc).__name__ if exc else code)[:200],
            message=said,
            where=where[:300],
            path=subject[:500],
            method="",
            trace=trace,
            context=kept,
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
            raced = _open(db, owner_id=owner_id, mark=mark)
            if raced is not None:
                return raced.reference
            continue
        _tell(row.id)
        return row.reference
    logger.error("a fault reference could not be drawn", extra={"subject": subject})
    return ""


def _open(db: Session, *, owner_id: uuid.UUID, mark: str) -> ErrorEvent | None:
    return db.scalar(
        select(ErrorEvent).where(
            ErrorEvent.owner_id == owner_id,
            ErrorEvent.fingerprint == mark,
            ErrorEvent.resolved_at.is_(None),
        )
    )


def _fingerprint(*, code: str, where: str, exc: BaseException | None) -> str:
    """The same fault: the same code at the same place, and with an exception
    the same exception from the same line of ours."""
    seed = f"{code}|{where}"
    if exc is not None:
        frame = _ours(exc.__traceback__)
        place = f"{frame[0]}:{frame[1]}" if frame else ""
        seed += f"|{type(exc).__module__}.{type(exc).__name__}|{place}"
    return hashlib.sha256(seed.encode()).hexdigest()[:64]


def _plain(value: dict[str, Any]) -> dict[str, Any]:
    """JSON the column takes: ids, dates and the like as text."""
    loaded = json.loads(json.dumps(value, default=str, ensure_ascii=False))
    return loaded if isinstance(loaded, dict) else {}


def _tell(event_id: uuid.UUID) -> None:
    try:
        hooks.fire(FAULT_HOOK, event_id=str(event_id))
    except Exception:
        logger.exception("fault hook failed", extra={"event": str(event_id)})
