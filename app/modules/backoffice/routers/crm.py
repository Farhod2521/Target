"""A customer's CRM from their card: its figures, and the owner's settings run by staff.

Support, Finance and Owner; erasing the whole CRM is the Owner's alone. Each
write is the cabinet's own and goes to the journal with its reason; a password
never does. A write names its pair: one that has left answers 404 rather than
falling back on the cabinet's current pair, and landing on another CRM.
"""

import uuid
from dataclasses import asdict
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field, StringConstraints
from sqlalchemy.orm import Session

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice import services
from app.modules.backoffice.constants import ADMIN_ROLES, ActionKind, Role
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.schemas import CustomerCrmOut, MessageOut
from app.modules.backoffice.selectors.card import person
from app.modules.backoffice.selectors.crm import (
    crm_totals,
    pair_figures,
    pair_lines,
)
from app.modules.crm import selectors as crm_selectors
from app.modules.crm import services as crm
from app.modules.crm.constants import SetupState, Since
from app.modules.crm.routers import PAIR_Q, WrittenIn, settings_out
from app.modules.crm.selectors import Viewer, office_viewer

router = APIRouter(prefix="/customers/{customer_id}/crm")
Admin = Annotated[User, Depends(staff_required(*ADMIN_ROLES))]
Owner = Annotated[User, Depends(staff_required(Role.OWNER))]
Reason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


def _customer(db: Session, customer_id: uuid.UUID) -> User:
    customer = person(db, customer_id=customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return customer


def working_viewer(
    customer_id: uuid.UUID,
    db: Db,
    actor: Admin,
    pair: str = Query(
        min_length=1, max_length=160, description="The pair this write is for."
    ),
) -> Viewer:
    viewer = office_viewer(
        db, customer=_customer(db, customer_id), staff=actor, wanted=pair
    )
    if viewer.pair is None or viewer.pair.key != pair:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return viewer


Working = Annotated[Viewer, Depends(working_viewer)]


def _done(
    db: Session,
    viewer: Viewer,
    *,
    kind: ActionKind,
    reason: str,
    message: str,
    **detail: Any,
) -> dict[str, Any]:
    assert viewer.pair is not None
    services.record(
        db,
        customer=viewer.owner,
        actor=viewer.user,
        kind=kind,
        reason=reason,
        detail={"pair": viewer.pair.key, **detail},
    )
    db.commit()
    return {"message": message}


class WhyIn(WrittenIn):
    reason: Reason = Field(description="Why - it goes to the journal.")


class CrmStateIn(WhyIn):
    on: bool


class CrmStageIn(WhyIn):
    name: str = Field(max_length=48)
    color: str = ""


class StageMoveIn(WrittenIn):
    way: str = "right"
    reason: str = Field("", max_length=500)


class QualityIn(WhyIn):
    quality: list[str] = Field(default_factory=list)


class CrmDistributionIn(WhyIn):
    distribution: str


class FlowIn(WhyIn):
    since: str = Since.WEEK
    day: date | None = None
    every_ad: bool = True
    ad: list[str] = Field(default_factory=list)
    offered: list[str] = Field(default_factory=list)
    take_new_ads: bool = False


class LostReasonIn(WhyIn):
    name: str = Field(max_length=64)


class MemberAddIn(WhyIn):
    name: str
    email: str
    password: str = Field(max_length=128)
    kpi_fix: str = ""
    kpi_percent: str = ""


class MemberEditIn(WhyIn):
    name: str
    takes_leads: bool = True
    kpi_fix: str = ""
    kpi_percent: str = ""


class CrmMemberPasswordIn(WhyIn):
    password: str = Field(max_length=128)


class EraseIn(WhyIn):
    email: str = Field(description="The customer's address, typed back.")


@router.get("", responses={200: {"model": CustomerCrmOut}})
def customer_crm(
    customer_id: uuid.UUID, db: Db, actor: Admin, pair: str = PAIR_Q
) -> dict[str, Any]:
    """The CRM of one pair: settings, figures, and a line for each other pair."""
    customer = _customer(db, customer_id)
    viewer = office_viewer(db, customer=customer, staff=actor, wanted=pair)
    now = utcnow()
    lines, elsewhere = pair_lines(db, owner=customer, pairs=viewer.pairs)
    setup = crm_selectors.setup_of(db, scope=viewer.scope)
    figures = (
        pair_figures(db, owner=customer, pair=viewer.pair, scope=viewer.scope, now=now)
        if viewer.pair is not None and viewer.scope is not None
        else None
    )
    return settings_out(db, viewer) | {
        "pair_lines": [
            {
                "key": line.pair.key,
                "page": line.pair.page.name or line.pair.page.external_id,
                "account": line.pair.account.name or line.pair.account.external_id,
                "state": line.state,
                "cards": line.cards,
                "managers": line.managers,
            }
            for line in lines
        ],
        "cards_elsewhere": elsewhere,
        "totals": crm_totals(db, owner=customer).as_detail(),
        "enabled_at": setup.enabled_at if setup else None,
        "disabled_at": setup.disabled_at if setup else None,
        "seats": {
            "used": crm_selectors.team_size(db, owner=customer),
            "allowed": crm_selectors.seat_capacity(db, owner=customer, at=now),
        },
        "figures": (
            {
                **{
                    key: value
                    for key, value in asdict(figures).items()
                    if key not in ("stages", "managers")
                },
                "stages": [
                    {"stage_id": str(key), **asdict(value)}
                    for key, value in figures.stages.items()
                ],
                "managers": [
                    {"user_id": str(key), **asdict(value)}
                    for key, value in figures.managers.items()
                ],
            }
            if figures is not None
            else None
        ),
    }


@router.post("/state", responses={200: {"model": MessageOut}})
def change_state(body: CrmStateIn, db: Db, viewer: Working) -> dict[str, Any]:
    """Start or stop the board; stopped, nothing on it is lost."""
    if not body.on:
        crm.disable_crm(db, viewer=viewer)
        return _done(
            db,
            viewer,
            kind=ActionKind.CRM_STATE_CHANGED,
            reason=body.reason,
            message="CRM to'xtatildi.",
            state=SetupState.OFF,
        )
    placed = crm.enable_crm(db, viewer=viewer)
    return _done(
        db,
        viewer,
        kind=ActionKind.CRM_STATE_CHANGED,
        reason=body.reason,
        message=f"CRM yoqildi. Doskaga tushgan lidlar: {placed}.",
        state=SetupState.ON,
        placed=placed,
    )


@router.post("/stages", responses={200: {"model": MessageOut}})
def add_stage(body: CrmStageIn, db: Db, viewer: Working) -> dict[str, Any]:
    """One more column, before «Sotildi»."""
    stage = crm.add_stage(db, viewer=viewer, name=body.name, color=body.color)
    return _done(
        db,
        viewer,
        kind=ActionKind.CRM_STAGES_CHANGED,
        reason=body.reason,
        message="Ustun qo'shildi.",
        added=stage.name,
    )


@router.put("/stages/{stage_id}", responses={200: {"model": MessageOut}})
def edit_stage(
    stage_id: uuid.UUID, body: CrmStageIn, db: Db, viewer: Working
) -> dict[str, Any]:
    stage = crm.update_stage(
        db, viewer=viewer, stage_id=str(stage_id), name=body.name, color=body.color
    )
    return _done(
        db,
        viewer,
        kind=ActionKind.CRM_STAGES_CHANGED,
        reason=body.reason,
        message="Ustun saqlandi.",
        edited=stage.name,
    )


@router.post("/stages/{stage_id}/move", responses={200: {"model": MessageOut}})
def move_stage(
    stage_id: uuid.UUID, body: StageMoveIn, db: Db, viewer: Working
) -> dict[str, Any]:
    """One place along. The arrows take no reason: the journal still says who."""
    crm.move_stage(
        db,
        viewer=viewer,
        stage_id=str(stage_id),
        step=1 if body.way == "right" else -1,
    )
    return _done(
        db,
        viewer,
        kind=ActionKind.CRM_STAGES_CHANGED,
        reason=body.reason,
        message="Ustun tartibi o'zgardi.",
        moved=str(stage_id),
    )


@router.post("/stages/{stage_id}/delete", responses={200: {"model": MessageOut}})
def delete_stage(
    stage_id: uuid.UUID, body: WhyIn, db: Db, viewer: Working
) -> dict[str, Any]:
    """Its cards go to the first column."""
    moved = crm.delete_stage(db, viewer=viewer, stage_id=str(stage_id))
    return _done(
        db,
        viewer,
        kind=ActionKind.CRM_STAGES_CHANGED,
        reason=body.reason,
        message=f"Ustun o'chirildi. Birinchi ustunga o'tgan kartalar: {moved}.",
        deleted=str(stage_id),
        cards_moved=moved,
    )


@router.post("/quality", responses={200: {"model": MessageOut}})
def change_quality(body: QualityIn, db: Db, viewer: Working) -> dict[str, Any]:
    crm.save_quality(db, viewer=viewer, stage_ids=body.quality)
    return _done(
        db,
        viewer,
        kind=ActionKind.CRM_SETTINGS_CHANGED,
        reason=body.reason,
        message="Sifatli ustunlar saqlandi.",
        quality=body.quality,
    )


@router.post("/distribution", responses={200: {"model": MessageOut}})
def change_distribution(
    body: CrmDistributionIn, db: Db, viewer: Working
) -> dict[str, Any]:
    crm.save_distribution(db, viewer=viewer, distribution=body.distribution)
    return _done(
        db,
        viewer,
        kind=ActionKind.CRM_SETTINGS_CHANGED,
        reason=body.reason,
        message="Taqsimlash saqlandi.",
        distribution=body.distribution,
    )


@router.post("/flow", responses={200: {"model": MessageOut}})
def change_flow(body: FlowIn, db: Db, viewer: Working) -> dict[str, Any]:
    """Which leads land on the board."""
    crm.save_flow(
        db,
        viewer=viewer,
        since=body.since,
        day=body.day,
        every_ad=body.every_ad,
        ad_ids=body.ad,
        offered_ids=body.offered,
        take_new_ads=body.take_new_ads,
    )
    return _done(
        db,
        viewer,
        kind=ActionKind.CRM_SETTINGS_CHANGED,
        reason=body.reason,
        message="Lid oqimi saqlandi.",
        since=body.since,
        every_ad=body.every_ad,
    )


@router.post("/reasons", responses={200: {"model": MessageOut}})
def add_reason(body: LostReasonIn, db: Db, viewer: Working) -> dict[str, Any]:
    reason = crm.add_reason(db, viewer=viewer, name=body.name)
    return _done(
        db,
        viewer,
        kind=ActionKind.CRM_SETTINGS_CHANGED,
        reason=body.reason,
        message="Rad etish sababi qo'shildi.",
        added=reason.name,
    )


@router.post("/reasons/{reason_id}/delete", responses={200: {"model": MessageOut}})
def delete_reason(
    reason_id: uuid.UUID, body: WhyIn, db: Db, viewer: Working
) -> dict[str, Any]:
    crm.delete_reason(db, viewer=viewer, reason_id=str(reason_id))
    return _done(
        db,
        viewer,
        kind=ActionKind.CRM_SETTINGS_CHANGED,
        reason=body.reason,
        message="Rad etish sababi o'chirildi.",
        deleted=str(reason_id),
    )


@router.post("/members", responses={200: {"model": MessageOut}})
def add_member(body: MemberAddIn, db: Db, viewer: Working) -> dict[str, Any]:
    """A sales manager on this pair, with a login. They change the password when
    they first sign in."""
    member = crm.add_member(
        db,
        viewer=viewer,
        name=body.name,
        email=body.email,
        password=body.password,
        kpi_fix=body.kpi_fix,
        kpi_percent=body.kpi_percent,
    )
    return _done(
        db,
        viewer,
        kind=ActionKind.CRM_MEMBERS_CHANGED,
        reason=body.reason,
        message="Menejer qo'shildi.",
        added=member.user.email,
    )


@router.put("/members/{member_id}", responses={200: {"model": MessageOut}})
def edit_member(
    member_id: uuid.UUID, body: MemberEditIn, db: Db, viewer: Working
) -> dict[str, Any]:
    member = crm.update_member(
        db,
        viewer=viewer,
        member_id=str(member_id),
        name=body.name,
        takes_leads=body.takes_leads,
        kpi_fix=body.kpi_fix,
        kpi_percent=body.kpi_percent,
    )
    return _done(
        db,
        viewer,
        kind=ActionKind.CRM_MEMBERS_CHANGED,
        reason=body.reason,
        message="Menejer saqlandi.",
        edited=member.user.email,
    )


@router.post("/members/{member_id}/password", responses={200: {"model": MessageOut}})
def member_password(
    member_id: uuid.UUID, body: CrmMemberPasswordIn, db: Db, viewer: Working
) -> dict[str, Any]:
    """Signs the manager out everywhere; they change it when they next sign in."""
    member = crm.reset_member_password(
        db, viewer=viewer, member_id=str(member_id), password=body.password
    )
    return _done(
        db,
        viewer,
        kind=ActionKind.CRM_MEMBERS_CHANGED,
        reason=body.reason,
        message="Menejer paroli yangilandi.",
        password_of=member.user.email,
    )


@router.post("/members/{member_id}/delete", responses={200: {"model": MessageOut}})
def remove_member(
    member_id: uuid.UUID, body: WhyIn, db: Db, viewer: Working
) -> dict[str, Any]:
    """The login goes; their open cards return to the first column, unassigned."""
    released = crm.remove_member(db, viewer=viewer, member_id=str(member_id))
    return _done(
        db,
        viewer,
        kind=ActionKind.CRM_MEMBERS_CHANGED,
        reason=body.reason,
        message=f"Menejer o'chirildi. Bo'shagan kartalar: {released}.",
        removed=str(member_id),
        cards_released=released,
    )


@router.post("/erase", responses={200: {"model": MessageOut}})
def erase(
    customer_id: uuid.UUID, body: EraseIn, db: Db, actor: Owner
) -> dict[str, Any]:
    """The whole CRM, on every pair. Leads and bought seats stay. Owner only."""
    customer = _customer(db, customer_id)
    totals = services.erase_customer_crm(
        db,
        customer=customer,
        actor=actor,
        typed_email=body.email,
        reason=body.reason,
    )
    db.commit()
    return {
        "message": f"CRM o'chirildi: {totals.cards} ta karta, "
        f"{totals.managers} ta menejer."
    }
