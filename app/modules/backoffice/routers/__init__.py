"""The office's shell and journal, as JSON for the office frontend.

Every route answers 404 to a reader without the role, as Django's
``staff_required`` did.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice import selectors
from app.modules.backoffice.constants import ROLE_LABELS, Role
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.routers._out import choices, person_out, trace_out
from app.modules.backoffice.routers.actions import router as actions
from app.modules.backoffice.routers.advertising import router as advertising
from app.modules.backoffice.routers.customers import router as customers
from app.modules.backoffice.routers.dashboard import router as dashboard
from app.modules.backoffice.routers.payments import router as payments
from app.modules.backoffice.routers.promo import router as promo
from app.modules.backoffice.routers.refusals import router as refusals
from app.modules.backoffice.routers.support import router as support
from app.modules.backoffice.schemas import JournalOut, MeOut

router = APIRouter(prefix="/office", tags=["office"])
Staff = Annotated[User, Depends(staff_required(*Role))]
Owner = Annotated[User, Depends(staff_required(Role.OWNER))]
router.include_router(customers)
router.include_router(advertising)
router.include_router(actions)
router.include_router(promo)
router.include_router(support)
router.include_router(dashboard)
router.include_router(payments)
router.include_router(refusals)


@router.get("/me", responses={200: {"model": MeOut}})
def me(db: Db, user: Staff) -> dict[str, Any]:
    """Who is reading, which doors they may open, and what waits behind them."""
    shell = selectors.office_shell(db, user=user, now=utcnow())
    return {
        "user": person_out(user),
        "roles": [
            {"value": str(role), "label": str(ROLE_LABELS[role])}
            for role in Role
            if str(role) in shell.roles
        ],
        "can": {
            "give": shell.can_give,
            "grant": shell.can_grant,
            "owner": shell.is_owner,
            "superuser": shell.is_superuser,
            "engineer": shell.is_engineer,
            "answer_support": shell.can_answer,
            "answer_feedback": shell.may_answer_feedback,
            "sell": shell.can_sell,
            "lead_sales": shell.leads_sales,
        },
        "waiting": {
            "promos": shell.waiting_promos,
            "asks": shell.waiting_asks,
            "feedback": shell.waiting_feedback,
            "support": shell.waiting_support,
            "arizas": shell.waiting_arizas,
        },
    }


@router.get("/journal", responses={200: {"model": JournalOut}})
def journal(
    db: Db,
    user: Owner,
    kind: str = Query("", description="One kind's rows; empty is every write."),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The office's own log, newest first. Owner only."""
    page = selectors.journal(db, kind=kind, offset=offset)
    return {
        "kind": kind,
        "kinds": choices(selectors.kind_choices()),
        "rows": [
            {**trace_out(row), "customer": person_out(row.owner)} for row in page.rows
        ],
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
    }
