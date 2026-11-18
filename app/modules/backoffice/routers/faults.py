"""Our own faults, for the Developers (and the superuser), as JSON.

The office's «Developer» page: the open ones newest first, one by its
6-letter reference with its traceback and context, and «Hal qilindi».
Keys are camelCase: the page was built to this shape.
"""

import json
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.audit.constants import ACTION_TYPE_LABELS, ActionType
from app.modules.audit.models import ErrorEvent
from app.modules.audit.services import settle_error
from app.modules.backoffice.constants import FAULT_ROLES
from app.modules.backoffice.permissions import staff_required

router = APIRouter(prefix="/faults")
Developer = Annotated[User, Depends(staff_required(*FAULT_ROLES))]
LISTED: Final = 200
CODE_TITLES: Final[dict[str, str]] = {
    "unknown": "kutilmagan xato",
    "schema_error": "AI javobi noto'g'ri shaklda",
    "unavailable": "AI javob bermadi",
    "not_applied": "Meta qabul qildi, lekin bajarmadi",
    "stalled": "vaqtida bajarilmadi",
    "not_launchable": "yig'ilgan reklama Meta'ga yaroqsiz",
    "prep_failed": "tayyorlash to'xtadi",
    "ai_failed": "AI ishlamadi",
    "support_ticket": "Support dasturchiga berdi",
}


@router.get("")
def faults(db: Db, user: Developer) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ErrorEvent)
        .options(selectinload(ErrorEvent.owner))
        .where(ErrorEvent.resolved_at.is_(None))
        .order_by(ErrorEvent.last_seen_at.desc())
        .limit(LISTED)
    )
    return [_summary(row) for row in rows]


@router.get("/{reference}")
def fault(reference: str, db: Db, user: Developer) -> dict[str, Any]:
    return _detail(_found(db, reference))


@router.post("/{reference}/settle", status_code=status.HTTP_204_NO_CONTENT)
def settle(reference: str, db: Db, user: Developer) -> None:
    settle_error(db, event_id=str(_found(db, reference).id), by=user, now=utcnow())


def _found(db: Session, reference: str) -> ErrorEvent:
    row = db.scalar(
        select(ErrorEvent).where(ErrorEvent.reference == reference.strip().upper())
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return row


def _summary(row: ErrorEvent) -> dict[str, Any]:
    owner = row.owner
    return {
        "ref": row.reference,
        "title": _title(row),
        # Nobody marks a fault as looked at yet: open is new until settled.
        "state": "new",
        "times": row.seen,
        "customers": 1,
        "customerName": owner.full_name or owner.email,
        "lastAt": row.last_seen_at.isoformat(),
    }


def _detail(row: ErrorEvent) -> dict[str, Any]:
    owner = row.owner
    context = row.context or {}
    stack = "\n\n".join(
        part
        for part in (
            f"Xato: {row.message}" if row.message else "",
            row.trace,
            "Kontekst:\n" + json.dumps(context, ensure_ascii=False, indent=2),
        )
        if part
    )
    return {
        **_summary(row),
        "settled": row.resolved_at is not None,
        "kind": str(context.get("code") or row.exception),
        "customer": {
            "id": str(owner.id),
            "name": owner.full_name or owner.email,
            "initials": _initials(owner.full_name or owner.email),
            "business": "",
        },
        "screen": row.where,
        "url": row.path,
        "at": row.created_at.isoformat(),
        "device": "",
        "stack": stack,
        # What the client's screen said is not kept; the page hides it.
        "shown": "",
    }


def _title(row: ErrorEvent) -> str:
    context = row.context or {}
    code = str(context.get("code") or row.exception)
    said = CODE_TITLES.get(code, code)
    return f"{_subject(row.path, str(context.get('action') or ''))} — {said}"


def _subject(path: str, action: str) -> str:
    """What the fault was about, by the subject kept and, for a press, the
    action kept in its context."""
    kind = path.partition(":")[0]
    if kind == "launch":
        return "Reklama yaratish"
    if kind == "ticket":
        return "Support zayavkasi"
    if kind == "action":
        if action in ActionType.values:
            return str(ACTION_TYPE_LABELS[ActionType(action)])
        return action or "Amal"
    return path or "Xato"


def _initials(name: str) -> str:
    words = [word for word in name.replace("@", " ").split() if word]
    return "".join(word[0] for word in words[:2]).upper() or "?"
