"""The office's advertising figures, and which campaigns and plans they count.

``GET /office/acquisition`` is the six figures for one window of days, read
by Finance and the Owner (the money roles), as the dashboard's money is; the
window is asked as the dashboard's is. The path does not say «ad»: ad
blockers drop such paths.

``/campaigns`` and ``/plans`` are the superuser's alone (everyone else gets
404): which campaigns of the office's ad account (``OFFICE_AD_ACCOUNT``) and
which plans count. The campaigns are those Meta still lists and those only
the daily figures remember. Setting either replaces its whole picked set.
"""

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete

from app.api.deps import Db
from app.common.config import settings
from app.common.exceptions import InputRefused
from app.modules.accounts.models import User
from app.modules.backoffice.constants import MONEY_ROLES
from app.modules.backoffice.models import OfficeAcquisitionPlan, OfficeAdCampaign
from app.modules.backoffice.permissions import staff_required, superuser_required
from app.modules.backoffice.routers._out import amounts
from app.modules.backoffice.routers.dashboard import (
    PERIOD_Q,
    SINCE_Q,
    UNTIL_Q,
    _window,
    window_out,
)
from app.modules.backoffice.schemas import (
    OfficeAcquisitionPlansOut,
    OfficeAdCampaignsOut,
    OfficeAdFiguresOut,
)
from app.modules.backoffice.selectors.ad_figures import (
    EXACT_FROM,
    ad_figures,
    campaign_rows,
    office_account,
    plan_rows,
)

router = APIRouter(prefix="/acquisition")
Money = Annotated[User, Depends(staff_required(*MONEY_ROLES))]
Superuser = Annotated[User, Depends(superuser_required)]
MOST = 500


class PlansIn(BaseModel):
    plan_ids: list[uuid.UUID] = Field(
        max_length=MOST, description="Plan ids; the whole picked set."
    )


class PickIn(BaseModel):
    campaign_ids: list[str] = Field(
        max_length=MOST, description="Meta campaign ids; the whole picked set."
    )


@router.get("", responses={200: {"model": OfficeAdFiguresOut}})
def figures(
    db: Db,
    user: Money,
    period: str = PERIOD_Q,
    since: date | None = SINCE_Q,
    until: date | None = UNTIL_Q,
) -> dict[str, Any]:
    """Spend, revenue, ROAS, CAC, conversion and deal time for the window."""
    window = _window(period=period, since=since, until=until)
    found = ad_figures(db, window=window)
    return {
        "window": window_out(window),
        "account": found.account_name,
        "account_found": found.account_found,
        "picked": found.picked,
        "can_pick": bool(user.is_superuser),
        "spend": amounts(found.spend),
        "spend_uzs_minor": found.spend_home_minor,
        "unpriced_days": found.unpriced_days,
        "plans_picked": found.plans_picked,
        "signups": found.signups,
        "payers": found.payers,
        "revenue_uzs_minor": found.revenue_minor,
        "roas": found.roas,
        "cac_uzs_minor": found.cac_minor,
        "conversion_pct": found.conversion_pct,
        "deals": found.deals,
        "deal_seconds": found.deal_seconds,
        "estimated_from": found.estimated_from,
        "estimated_until": found.estimated_until,
        "exact_from": EXACT_FROM,
    }


def _campaigns_out(db: Db) -> dict[str, Any]:
    account = office_account(db)
    rows = campaign_rows(db, account) if account else []
    return {
        "account": account.name if account else "",
        "account_id": settings.office_ad_account,
        "account_found": account is not None,
        "currency": account.currency if account else "",
        "campaigns": [
            {
                "id": row.external_id,
                "name": row.name,
                "status": row.status,
                "sites": list(row.sites),
                "first_day": row.first_day,
                "last_day": row.last_day,
                "spend_minor": row.spend_minor,
                "leads": row.leads,
                "picked": row.picked,
            }
            for row in rows
        ],
    }


@router.get("/campaigns", responses={200: {"model": OfficeAdCampaignsOut}})
def campaigns(db: Db, user: Superuser) -> dict[str, Any]:
    """The office account's campaigns, the newest first, each marked picked or not."""
    return _campaigns_out(db)


@router.put("/campaigns", responses={200: {"model": OfficeAdCampaignsOut}})
def pick_campaigns(body: PickIn, db: Db, user: Superuser) -> dict[str, Any]:
    """Count exactly these campaigns from now on."""
    account = office_account(db)
    if account is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Ofis reklama akkaunti hech bir kabinetda yo'q."
        )
    wanted = {raw.strip() for raw in body.campaign_ids if raw.strip()}
    known = {row.external_id for row in campaign_rows(db, account)}
    foreign = sorted(wanted - known)
    if foreign:
        raise InputRefused(
            {
                "campaign_ids": f"Bu kampaniyalar {account.name} akkauntida "
                f"yo'q: {', '.join(foreign)}"
            }
        )
    db.execute(delete(OfficeAdCampaign))
    db.add_all(
        OfficeAdCampaign(campaign_external_id=external_id, picked_by_id=user.id)
        for external_id in sorted(wanted)
    )
    db.commit()
    return _campaigns_out(db)


def _plans_out(db: Db) -> dict[str, Any]:
    return {
        "plans": [
            {
                "id": row.id,
                "name": row.name,
                "code": row.code,
                "is_active": row.is_active,
                "paid": row.paid,
                "picked": row.picked,
            }
            for row in plan_rows(db)
        ]
    }


@router.get("/plans", responses={200: {"model": OfficeAcquisitionPlansOut}})
def plans(db: Db, user: Superuser) -> dict[str, Any]:
    """Every plan, each marked counted or not."""
    return _plans_out(db)


@router.put("/plans", responses={200: {"model": OfficeAcquisitionPlansOut}})
def pick_plans(body: PlansIn, db: Db, user: Superuser) -> dict[str, Any]:
    """Count exactly these plans' payments from now on."""
    wanted = set(body.plan_ids)
    known = {uuid.UUID(row.id) for row in plan_rows(db)}
    foreign = sorted(str(plan) for plan in wanted - known)
    if foreign:
        raise InputRefused({"plan_ids": f"Bunday tarif yo'q: {', '.join(foreign)}"})
    db.execute(delete(OfficeAcquisitionPlan))
    db.add_all(
        OfficeAcquisitionPlan(plan_id=plan, picked_by_id=user.id) for plan in wanted
    )
    db.commit()
    return _plans_out(db)
