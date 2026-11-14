"""Shutting an account and opening it again, with the reason it is told.

A block names a reason from the super admin's list, whether the account may
read it, and a note only the office sees. The system blocks nothing itself:
it files a suggestion, and a person in Support decides.
"""

from datetime import datetime
from typing import Any, Final

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.db import on_commit, utcnow
from app.common.hooks import fire
from app.modules.accounts.constants import (
    BLOCKED_MESSAGE,
    BLOCKED_REASON_HEAD,
    OWNER_BLOCKED_MESSAGE,
    BlockCode,
    SuggestionOutcome,
)
from app.modules.accounts.models import (
    AccountBlock,
    BlockReason,
    BlockSuggestion,
    User,
)
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit

BLOCK_SUGGESTED: Final = "accounts.block_suggested"

# The words a reason starts with when the code needs it before anyone wrote
# it; the super admin may change them later.
_SEEDED: Final = {
    BlockCode.META_IDENTITY_REUSED: (
        "Bitta Facebook bilan ikkinchi kabinet",
        "Bu Facebook akkaunt boshqa kabinetga ulangan. Bitta Facebook akkaunt "
        "bitta kabinetda ishlaydi.",
        "Этот аккаунт Facebook подключён к другому кабинету. Один аккаунт "
        "Facebook работает только в одном кабинете.",
        "This Facebook account is connected to another cabinet. One Facebook "
        "account works in one cabinet only.",
    ),
    BlockCode.GOOGLE_IDENTITY_REUSED: (
        "Bitta Google bilan ikkinchi kabinet",
        "Bu Google akkaunt boshqa kabinetga ulangan. Bitta Google akkaunt "
        "bitta kabinetda ishlaydi.",
        "Этот аккаунт Google подключён к другому кабинету. Один аккаунт "
        "Google работает только в одном кабинете.",
        "This Google account is connected to another cabinet. One Google "
        "account works in one cabinet only.",
    ),
    BlockCode.OTHER: ("Boshqa", "", "", ""),
}


def known_reason(db: Session, *, code: BlockCode) -> BlockReason:
    """The reason the code names, made with its first words if missing."""
    found = db.scalar(select(BlockReason).where(BlockReason.code == str(code)))
    if found is not None:
        return found
    name, uz, ru, en = _SEEDED[code]
    found = BlockReason(
        code=str(code),
        name=name,
        message_uz=uz,
        message_ru=ru,
        message_en=en,
        position=len(_SEEDED) if code == BlockCode.OTHER else 0,
    )
    db.add(found)
    db.flush()
    return found


def open_block(db: Session, *, user: User) -> AccountBlock | None:
    return db.scalar(
        select(AccountBlock).where(
            AccountBlock.owner_id == user.id, AccountBlock.lifted_at.is_(None)
        )
    )


def block_user(
    db: Session,
    *,
    user: User,
    reason: BlockReason,
    shown_to_user: bool,
    note: str = "",
    actor: User | None = None,
    now: datetime | None = None,
) -> User:
    if not user.is_active:
        return user
    now = now or utcnow()
    user.is_active = False
    db.add(
        AccountBlock(
            owner_id=user.id,
            reason_id=reason.id,
            shown_to_user=shown_to_user,
            note=note.strip(),
            blocked_by_id=actor.id if actor else None,
            blocked_at=now,
        )
    )
    _resolve_suggestions(
        db, owner=user, outcome=SuggestionOutcome.BLOCKED, actor=actor, now=now
    )
    emit(
        db,
        owner_id=user.id,
        name=EventName.USER_BLOCKED,
        aggregate_type="user",
        aggregate_id=user.id,
        payload={
            "reason": reason.code or reason.name,
            "reason_id": str(reason.id),
            "shown_to_user": shown_to_user,
            **({"actor_id": str(actor.id)} if actor else {}),
        },
    )
    db.flush()
    _hold_ads(db, user=user, blocked=True)
    return user


def _hold_ads(db: Session, *, user: User, blocked: bool) -> None:
    """What the account launched here follows the block: stopped at once and
    deleted at Meta a day later, given back if it is opened again in time."""
    owner_id = str(user.id)

    def send() -> None:
        from app.modules.ads import tasks

        task = (
            tasks.hold_blocked_owner_task
            if blocked
            else tasks.release_unblocked_owner_task
        )
        task.delay(owner_id)

    on_commit(db, send)


def unblock_user(
    db: Session,
    *,
    user: User,
    note: str,
    actor: User | None = None,
    now: datetime | None = None,
) -> User:
    if user.is_active:
        return user
    now = now or utcnow()
    user.is_active = True
    db.execute(
        update(AccountBlock)
        .where(AccountBlock.owner_id == user.id, AccountBlock.lifted_at.is_(None))
        .values(
            lifted_at=now,
            lifted_by_id=actor.id if actor else None,
            lift_note=note.strip(),
            updated_at=now,
        )
    )
    emit(
        db,
        owner_id=user.id,
        name=EventName.USER_UNBLOCKED,
        aggregate_type="user",
        aggregate_id=user.id,
        payload={"reason": note, **({"actor_id": str(actor.id)} if actor else {})},
    )
    db.flush()
    _hold_ads(db, user=user, blocked=False)
    return user


def blocked_message(db: Session, *, user: User) -> str:
    """What a blocked account reads at sign-in, in its own language: its
    reason when the block is shown to it, else only that it is blocked."""
    language = user.language if user.language in BLOCKED_MESSAGE else "uz"
    plain = BLOCKED_MESSAGE[language]
    block = open_block(db, user=user)
    if block is None or not block.shown_to_user:
        return plain
    reason = block.reason
    words = (getattr(reason, f"message_{language}", "") or reason.message_uz).strip()
    return f"{BLOCKED_REASON_HEAD[language]} {words}" if words else plain


def owner_blocked_message(*, user: User) -> str:
    """A CRM manager's login, refused because the cabinet's owner is shut."""
    return OWNER_BLOCKED_MESSAGE.get(user.language, OWNER_BLOCKED_MESSAGE["uz"])


def suggest_block(
    db: Session,
    *,
    owner: User,
    code: BlockCode,
    detail: dict[str, Any],
    now: datetime | None = None,
) -> BlockSuggestion | None:
    """File (or count again) a suggestion that Support block this account.

    Nothing for an account already shut or a colleague's own. Support is told
    once, when the suggestion is new; a repeat only counts.
    """
    if not owner.is_active or owner.is_staff:
        return None
    now = now or utcnow()
    reason = known_reason(db, code=code)
    found = db.scalar(
        select(BlockSuggestion).where(
            BlockSuggestion.owner_id == owner.id,
            BlockSuggestion.reason_id == reason.id,
            BlockSuggestion.resolved_at.is_(None),
        )
    )
    if found is not None:
        found.times += 1
        found.last_at = now
        found.detail = {**(found.detail or {}), **detail}
        db.flush()
        return found
    found = BlockSuggestion(
        owner_id=owner.id, reason_id=reason.id, detail=detail, last_at=now
    )
    db.add(found)
    db.flush()
    suggestion_id = str(found.id)
    on_commit(db, lambda: fire(BLOCK_SUGGESTED, suggestion_id=suggestion_id))
    return found


def dismiss_suggestion(
    db: Session,
    *,
    suggestion: BlockSuggestion,
    actor: User,
    note: str,
    now: datetime | None = None,
) -> BlockSuggestion:
    suggestion.resolved_at = now or utcnow()
    suggestion.resolved_by_id = actor.id
    suggestion.resolution = str(SuggestionOutcome.DISMISSED)
    suggestion.note = note.strip()
    db.flush()
    return suggestion


def _resolve_suggestions(
    db: Session,
    *,
    owner: User,
    outcome: SuggestionOutcome,
    actor: User | None,
    now: datetime,
) -> None:
    db.execute(
        update(BlockSuggestion)
        .where(
            BlockSuggestion.owner_id == owner.id,
            BlockSuggestion.resolved_at.is_(None),
        )
        .values(
            resolved_at=now,
            resolved_by_id=actor.id if actor else None,
            resolution=str(outcome),
            updated_at=now,
        )
    )
