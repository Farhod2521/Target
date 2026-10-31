"""Writing the business directions.

A direction is a name over a catalogue preset. The profile copies the preset
into ``Business.category`` when it is saved, so moving a direction's preset
moves the profiles standing on it in the same write: left behind, they would
keep a catalogue the direction no longer names. A direction belongs to no
customer, so its journal row is filed under the member of staff who wrote it.
"""

import logging
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.exceptions import DirectionInUse
from app.modules.backoffice.selectors.directions import businesses_on
from app.modules.backoffice.services.journal import record
from app.modules.businesses.models import Business, BusinessCategory

logger = logging.getLogger(__name__)

# The columns an office edit can move, with the label the journal shows.
TRACKED = {
    "key": "Kalit",
    "label_uz": "Nomi (uz)",
    "label_ru": "Nomi (ru)",
    "label_en": "Nomi (en)",
    "preset_key": "Katalog",
    "position": "Tartib",
    "is_active": "Faol",
}


def create_direction(
    db: Session, *, data: dict[str, Any], actor: User
) -> BusinessCategory:
    row = BusinessCategory(**data)
    db.add(row)
    db.flush()
    _journal(
        db,
        actor=actor,
        kind=ActionKind.DIRECTION_CREATED,
        direction=row,
        changed=_changes(before={}, after=_snapshot(row)),
    )
    logger.info("direction %s created by %s", row.key, actor.id)
    return row


def update_direction(
    db: Session, *, direction: BusinessCategory, data: dict[str, Any], actor: User
) -> BusinessCategory:
    """Rewrite a direction; the profiles on it follow its preset."""
    before = _snapshot(direction)
    for name, value in data.items():
        setattr(direction, name, value)
    db.flush()
    moved = db.execute(
        update(Business)
        .where(
            Business.direction_id == direction.id,
            Business.category != direction.preset_key,
        )
        .values(category=direction.preset_key, updated_at=utcnow())
    ).rowcount
    _journal(
        db,
        actor=actor,
        kind=ActionKind.DIRECTION_UPDATED,
        direction=direction,
        changed=_changes(before=before, after=_snapshot(direction)),
        moved=moved,
    )
    logger.info(
        "direction %s updated by %s, %s profiles moved",
        direction.key,
        actor.id,
        moved,
    )
    return direction


def delete_direction(db: Session, *, direction: BusinessCategory, actor: User) -> None:
    """Delete a direction nobody stands on; a used one is switched off instead."""
    count = businesses_on(db, direction=direction)
    if count:
        raise DirectionInUse(count=count)
    _journal(
        db,
        actor=actor,
        kind=ActionKind.DIRECTION_DELETED,
        direction=direction,
        changed={},
    )
    db.delete(direction)
    db.flush()
    logger.info("direction %s deleted by %s", direction.key, actor.id)


def _snapshot(row: BusinessCategory) -> dict[str, str]:
    """The tracked columns as the text a colleague reads in the journal."""
    return {name: str(getattr(row, name)) for name in TRACKED}


def _changes(*, before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    """Each column that moved, under its own label, as [was, now]."""
    return {
        label: [before.get(name, ""), after[name]]
        for name, label in TRACKED.items()
        if before.get(name, "") != after[name]
    }


def _journal(
    db: Session,
    *,
    actor: User,
    kind: ActionKind,
    direction: BusinessCategory,
    changed: dict[str, list[str]],
    moved: int = 0,
) -> None:
    record(
        db,
        customer=actor,
        actor=actor,
        kind=kind,
        detail={"key": direction.key, "changed": changed, "moved": moved},
    )
