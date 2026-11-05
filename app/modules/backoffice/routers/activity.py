"""«Harakatlar» on a customer's card: what happened on the account, from every
log that keeps it. Read only; Support, Finance and Owner."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import Db
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ADMIN_ROLES
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.routers._out import choices
from app.modules.backoffice.schemas import ActivityOut
from app.modules.backoffice.selectors.activity import (
    FEED_PAGE,
    GROUPS,
    WHO,
    activity,
)
from app.modules.backoffice.selectors.card import person

router = APIRouter(prefix="/customers/{customer_id}")
Admin = Annotated[User, Depends(staff_required(*ADMIN_ROLES))]

GROUP_LABELS = {
    "akkaunt": "Akkaunt",
    "tolov": "To'lovlar",
    "ulanish": "Ulanishlar",
    "reklama": "Reklama",
    "crm": "CRM",
    "aloqa": "Yordam va fikrlar",
    "sotuv": "Sotuv",
    "kontent": "Montaj",
    "ofis": "Ofis",
}
WHO_LABELS = {
    "customer": "Mijoz",
    "manager": "Menejer",
    "system": "Tizim",
    "agent": "AI agent",
    "staff": "Ofis xodimi",
}


@router.get("/activity", responses={200: {"model": ActivityOut}})
def customer_activity(
    customer_id: uuid.UUID,
    db: Db,
    actor: Admin,
    group: str = Query("", description="One of `groups`; empty is all."),
    who: str = Query("", description="One of `who`; empty is anyone."),
    before: datetime | None = Query(
        None, description="`next_before` of the last page."
    ),
    limit: int = Query(FEED_PAGE, ge=1, le=200),
) -> dict[str, Any]:
    """Newest first. Leads arriving are not on it; the CRM tab counts them."""
    customer = person(db, customer_id=customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if (group and group not in GROUPS) or (who and who not in WHO):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT)
    page = activity(
        db, owner=customer, group=group, who=who, before=before, limit=limit
    )
    return {
        "groups": choices([(g, GROUP_LABELS[g]) for g in GROUPS]),
        "who": choices([(w, WHO_LABELS[w]) for w in WHO]),
        "rows": [row.__dict__ for row in page.rows],
        "next_before": page.next_before,
    }
