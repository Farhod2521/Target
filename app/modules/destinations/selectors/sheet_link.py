"""Reads of the owner's spreadsheet link."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.common.cache import cache
from app.common.config import settings
from app.common.crypto import decrypt
from app.modules.accounts.models import User
from app.modules.destinations.constants import BrokenReason, SheetStatus
from app.modules.destinations.models import FormSheet, SheetLink


def sheets_enabled() -> bool:
    """Whether this deployment has a Google client at all: the whole off switch."""
    return bool(settings.google_oauth_client_id)


def picker_enabled() -> bool:
    """Whether "O'z faylimga" can be offered: Google's picker is set up."""
    return bool(
        sheets_enabled()
        and settings.google_picker_api_key
        and settings.google_cloud_project_number
    )


def picker_cache_key(*, owner_id: object) -> str:
    return f"destinations:picker:{owner_id}"


@dataclass(frozen=True, slots=True)
class PickerSetup:
    """What the browser needs to open Google's picker for one owner."""

    token: str
    api_key: str
    app_id: str


def picker_setup(*, owner: User) -> PickerSetup | None:
    """The picker's inputs, or ``None`` when the token has run out."""
    stored = cache.get(picker_cache_key(owner_id=owner.id))
    if not stored or not picker_enabled():
        return None
    return PickerSetup(
        token=decrypt(str(stored).encode()),
        api_key=settings.google_picker_api_key,
        app_id=settings.google_cloud_project_number,
    )


def picker_ready(*, owner: User) -> bool:
    """Whether the picker would open now: set up, and a token still waiting."""
    return (
        picker_enabled() and cache.get(picker_cache_key(owner_id=owner.id)) is not None
    )


def form_sheets_for(db: Session, *, link: SheetLink) -> list[FormSheet]:
    """The per-form files this owner has, oldest first, with their forms."""
    return list(
        db.scalars(
            select(FormSheet)
            .options(joinedload(FormSheet.form))
            .where(FormSheet.owner_id == link.owner_id)
            .order_by(FormSheet.created_at)
        )
    )


def sheet_link_for(db: Session, *, owner: User) -> SheetLink | None:
    """This owner's link, whatever state it is in, or ``None``."""
    return db.scalar(
        select(SheetLink)
        .options(joinedload(SheetLink.only_form))
        .where(SheetLink.owner_id == owner.id)
        .order_by(SheetLink.created_at.desc())
        .limit(1)
    )


def locked_link_for(db: Session, *, owner: User) -> SheetLink | None:
    """This owner's link, locked for the press that changes it."""
    return db.scalar(
        select(SheetLink)
        .where(SheetLink.owner_id == owner.id)
        .order_by(SheetLink.created_at.desc())
        .limit(1)
        .with_for_update(),
        execution_options={"populate_existing": True},
    )


def due_links(db: Session, *, status: SheetStatus, now: datetime) -> list[SheetLink]:
    """Links in ``status`` that are not waiting out a backoff. Every owner's."""
    return list(
        db.scalars(
            select(SheetLink)
            .where(
                SheetLink.status == status,
                or_(
                    SheetLink.next_attempt_at.is_(None),
                    SheetLink.next_attempt_at <= now,
                ),
            )
            .order_by(SheetLink.created_at)
        )
    )


def links_owing_revocation(db: Session) -> list[uuid.UUID]:
    """Disconnected links whose token was never handed back to Google."""
    return list(
        db.scalars(
            select(SheetLink.id)
            .where(
                SheetLink.status == SheetStatus.DISCONNECTED,
                SheetLink.token_fingerprint != "",
            )
            .order_by(SheetLink.updated_at)
        )
    )


def checkable_links(db: Session, *, link_id: str | None = None) -> list[SheetLink]:
    """Working links, and links stopped because their file went to the bin."""
    in_the_bin = and_(
        SheetLink.status == SheetStatus.BROKEN,
        SheetLink.broken_reason == BrokenReason.TRASHED,
    )
    query = (
        select(SheetLink)
        .where(or_(SheetLink.status == SheetStatus.ACTIVE, in_the_bin))
        .order_by(SheetLink.created_at)
    )
    if link_id is not None:
        query = query.where(SheetLink.id == _uuid(link_id))
    return list(db.scalars(query, execution_options={"populate_existing": True}))


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


__all__ = [
    "PickerSetup",
    "checkable_links",
    "due_links",
    "form_sheets_for",
    "links_owing_revocation",
    "locked_link_for",
    "picker_cache_key",
    "picker_enabled",
    "picker_ready",
    "picker_setup",
    "sheet_link_for",
    "sheets_enabled",
]
