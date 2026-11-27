"""Saying what kind of business a business is.

The direction is the profile's own (``Business.direction_id`` and the
catalogue it copies into ``category``), written here the way a saved
profile writes it. The narrower kind and how sure both are live beside the
business's knowledge. A kind we guessed from the page is ``guessed`` until
somebody of the business says yes; a guess never overwrites a kind somebody
confirmed.
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services.emit import emit
from app.modules.businesses.constants import KnowledgeSource, TypeState
from app.modules.businesses.exceptions import BadSubtype
from app.modules.businesses.models import (
    Business,
    BusinessCategory,
    BusinessKnowledge,
    BusinessSubtype,
)
from app.modules.businesses.services.knowledge import home, locked_row
from app.modules.businesses.services.subtypes import kept

logger = logging.getLogger(__name__)


def set_kind(
    db: Session,
    *,
    business: Business,
    direction: BusinessCategory,
    subtype: BusinessSubtype | None = None,
    state: str = TypeState.CONFIRMED,
    source: str = KnowledgeSource.OWNER,
    actor: User | None = None,
    now: datetime | None = None,
) -> BusinessKnowledge:
    """Write the business's direction and narrower kind; flushes.

    Answers the knowledge row. A ``guessed`` kind for a business whose kind
    is already ``confirmed`` changes nothing.
    """
    now = now or utcnow()
    if str(state) not in (TypeState.GUESSED, TypeState.CONFIRMED):
        raise BadSubtype("Holat noto'g'ri.")
    if subtype is not None:
        subtype = kept(db, subtype)
        if subtype.direction_id != direction.id:
            raise BadSubtype("Bu yo'nalish boshqa turga tegishli.")
    row = locked_row(db, business)
    if str(state) == TypeState.GUESSED and row.type_state == TypeState.CONFIRMED:
        return row
    profile = home(db, business)
    before = {
        "direction": str(profile.direction_id or ""),
        "category": profile.category,
        "subtype": str(row.subtype_id or ""),
        "state": row.type_state,
    }
    for one in {profile.id: profile, business.id: business}.values():
        # The relationships too: a reader later in this same session must
        # not meet the direction the row was loaded with.
        one.direction = direction
        one.direction_id = direction.id
        one.category = direction.preset_key
        one.custom_category = None
        one.custom_category_id = None
        one.updated_at = now
    row.subtype_id = subtype.id if subtype is not None else None
    row.type_state = str(state)
    row.updated_at = now
    db.flush()
    after = {
        "direction": str(direction.id),
        "category": direction.preset_key,
        "subtype": str(row.subtype_id or ""),
        "state": row.type_state,
    }
    if after != before:
        emit(
            db,
            owner_id=business.user_id,
            name=EventName.BUSINESS_TYPE_SET,
            aggregate_type="business",
            aggregate_id=profile.id,
            payload={
                "source": str(source),
                "by": str(actor.id) if actor is not None else "",
                "by_name": actor.full_name if actor is not None else "",
                "direction_key": direction.key,
                "direction_label": direction.label_uz,
                "subtype_name": subtype.name if subtype is not None else "",
                "before": before,
                "after": after,
            },
            occurred_at=now,
        )
    return row


__all__ = ["set_kind"]
