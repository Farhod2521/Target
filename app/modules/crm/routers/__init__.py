import uuid
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db, current_user
from app.common.db import get_db, utcnow
from app.modules.accounts.models import User
from app.modules.crm import selectors, services
from app.modules.crm.constants import (
    COLORS,
    DISTRIBUTION_LABELS,
    MAX_CUSTOM_STAGES,
    PRESET_LABELS,
    PRESETS,
    SINCE_LABELS,
    Distribution,
    SetupState,
    Since,
)
from app.modules.crm.models import CrmCard, CrmMember, CrmStage
from app.modules.crm.schemas import (
    BoardOut,
    CardOut,
    CardsMovedOut,
    CardsReleasedOut,
    CardViewOut,
    ColumnOut,
    DetailOut,
    MemberOut,
    NavOut,
    OkOut,
    PlacedOut,
    PulseOut,
    ReasonOut,
    SettingsOut,
    SetupStepOut,
    StageOut,
)
from app.modules.crm.selectors import Viewer

router = APIRouter(prefix="/crm", tags=["crm"])
STEPS = (1, 2, 3, 4)

SEARCH_Q = Query("", description="Search name or phone; first 80 characters are used.")
MEMBER_Q = Query("", description="Only cards of this member (user id).")
AD_Q = Query("", description="Only cards from this advert (Meta ad id).")
FLAG_Q = Query(
    "", description="`late` (due time passed) or `today` (due today); empty for all."
)
PAIR_Q = Query(
    "",
    max_length=160,
    description="The pair's CRM, as `page id:ad account id` from `pairs`; the "
    "cabinet's current pair when empty or unknown. A manager always gets their own.",
)


class Closed(HTTPException):
    def __init__(self, reason: str) -> None:
        super().__init__(status.HTTP_409_CONFLICT, detail={"crm": reason})


def crm_viewer(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    pair: str = PAIR_Q,
) -> Viewer:
    viewer = selectors.viewer_for(db, user=user, wanted=pair)
    if viewer.member is not None and viewer.member.is_active:
        if viewer.pair is None:
            raise Closed("no_pair")
        if not viewer.seated:
            raise Closed("seat")
    if not viewer.may_work:
        raise Closed("closed")
    if not selectors.crm_open(owner=viewer.owner):
        raise Closed("soon")
    if viewer.member is not None:
        if viewer.member.must_change_password:
            raise Closed("password")
        setup = selectors.setup_of(db, scope=viewer.scope)
        if setup is None or setup.state != SetupState.ON:
            raise Closed("off")
    return viewer


def owner_viewer(viewer: Viewer = Depends(crm_viewer)) -> Viewer:
    if not viewer.is_owner:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return viewer


def card_viewer(pk: uuid.UUID, db: Db, viewer: Viewer = Depends(crm_viewer)) -> Viewer:
    """The reader on the pair of card ``pk``: a card opened by its link opens
    whichever pair the owner's board is on."""
    found = selectors.viewer_on_card(db, viewer=viewer, card_id=str(pk))
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return found


def card_owner_viewer(viewer: Viewer = Depends(card_viewer)) -> Viewer:
    if not viewer.is_owner:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return viewer


def pairs_out(viewer: Viewer) -> dict[str, Any]:
    return {
        "pair": viewer.pair.key if viewer.pair is not None else None,
        "pairs": [
            {
                "key": pair.key,
                "page": pair.page.name or pair.page.external_id,
                "account": pair.account.name or pair.account.external_id,
            }
            for pair in (viewer.pairs if viewer.is_owner else ())
        ],
    }


def team_out(db: Session, viewer: Viewer) -> list[dict[str, Any]]:
    seated = selectors.seated_ids(db, owner=viewer.owner, at=utcnow())
    return [
        member_out(m, seated=m.id in seated)
        for m in selectors.active_members(db, scope=viewer.scope)
    ]


def _user(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": str(user.id), "full_name": user.full_name, "email": user.email}


def stage_out(stage: CrmStage) -> dict[str, Any]:
    return {
        "id": str(stage.id),
        "name": stage.name,
        "color": stage.color,
        "kind": stage.kind,
        "position": stage.position,
        "counts_as_quality": stage.counts_as_quality,
    }


def card_out(card: CrmCard, *, ads: dict[str, str] | None = None) -> dict[str, Any]:
    lead = card.lead
    return {
        "id": str(card.id),
        "stage_id": str(card.stage_id),
        "assignee": _user(card.assignee),
        "due_at": card.due_at,
        "due_note": card.due_note,
        "attempts": card.attempts,
        "last_note": card.last_note,
        "last_note_at": card.last_note_at,
        "returned": card.returned,
        "qualified_at": card.qualified_at,
        "won_amount_minor": card.won_amount_minor,
        "currency": card.currency,
        "lost_reason_name": card.lost_reason_name,
        "closed_at": card.closed_at,
        "taken_at": card.taken_at,
        "created_at": card.created_at,
        "lead": {
            "id": str(lead.id),
            "full_name": lead.full_name,
            "phone_e164": lead.phone_e164,
            "email": lead.email,
            "city": lead.city,
            "ad_external_id": lead.ad_external_id,
            "ad_title": (ads or {}).get(lead.ad_external_id, ""),
            "submitted_at": lead.submitted_at,
        },
    }


def member_out(member: CrmMember, *, seated: bool = True) -> dict[str, Any]:
    return {
        "id": str(member.id),
        "user": _user(member.user),
        "is_active": member.is_active,
        "seated": seated,
        "takes_leads": member.takes_leads,
        "must_change_password": member.must_change_password,
        "kpi_fix_minor": member.kpi_fix_minor,
        "kpi_percent": member.kpi_percent,
        "kpi_currency": member.kpi_currency,
    }


def column_out(column: selectors.Column, ads: dict[str, str]) -> dict[str, Any]:
    return {
        "stage": stage_out(column.stage),
        "cards": [card_out(card, ads=ads) for card in column.cards],
        "total": column.total,
        "won_minor": column.won_minor,
        "reasons": list(column.reasons),
        "start": column.start,
        "hidden": column.hidden,
        "next_start": column.next_start,
    }


@router.get("/nav", responses={200: {"model": NavOut}})
def nav(db: Db, user: CurrentUser, pair: str = PAIR_Q) -> dict[str, Any]:
    if user.crm_owner_id is not None or not selectors.crm_open(owner=user):
        return {"url": "/app/leads/", "attention": 0}
    count = 0
    if selectors.is_running(db, owner=user):
        count = selectors.attention_count(
            db, viewer=selectors.viewer_for(db, user=user, wanted=pair), now=utcnow()
        )
    return {"url": "/app/crm/", "attention": count}


@router.get("", responses={200: {"model": BoardOut}})
def board(
    db: Db,
    viewer: Viewer = Depends(crm_viewer),
    q: str = SEARCH_Q,
    m: str = MEMBER_Q,
    ad: str = AD_Q,
    f: str = FLAG_Q,
) -> dict[str, Any]:
    if viewer.pair is None:
        return {"setup_needed": False, "no_pair": True} | pairs_out(viewer)
    setup = selectors.setup_of(db, scope=viewer.scope)
    if viewer.is_owner and (setup is None or setup.state == SetupState.DRAFT):
        return {
            "setup_needed": True,
            "step": setup.step if setup else 1,
        } | pairs_out(viewer)
    now = utcnow()
    filters = selectors.read_filters(q=q, m=m, ad=ad, f=f)
    found = selectors.board(db, viewer=viewer, filters=filters, now=now)
    return pairs_out(viewer) | {
        "setup_needed": False,
        "no_pair": False,
        "running": setup is not None and setup.state == SetupState.ON,
        "is_owner": viewer.is_owner,
        "columns": [column_out(column, found.ads) for column in found.columns],
        "late": found.late,
        "today": found.today,
        "cursor": found.cursor,
        "filters": asdict(filters),
        "members": team_out(db, viewer),
        "ads": selectors.board_ads(db, viewer=viewer, now=now),
    }


@router.get(
    "/pulse",
    response_model=None,
    responses={
        200: {"model": PulseOut, "description": "The board changed."},
        204: {"description": "Nothing changed since `cursor`."},
    },
)
def pulse(
    db: Db,
    viewer: Viewer = Depends(crm_viewer),
    cursor: str = Query("", description="The `cursor` from the last answer."),
) -> dict[str, Any] | Response:
    now = selectors.cursor_of(db, viewer=viewer)
    if now == cursor:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return {
        "cursor": now,
        "layout_changed": selectors.layout_changed(before=cursor, now=now),
    }


@router.get("/columns/{pk}", responses={200: {"model": ColumnOut}})
def column(
    pk: uuid.UUID,
    db: Db,
    viewer: Viewer = Depends(crm_viewer),
    start: int = Query(
        0, ge=0, description="Skip this many cards; use the column's `next_start`."
    ),
    q: str = SEARCH_Q,
    m: str = MEMBER_Q,
    ad: str = AD_Q,
    f: str = FLAG_Q,
) -> dict[str, Any]:
    found = selectors.column_page(
        db,
        viewer=viewer,
        filters=selectors.read_filters(q=q, m=m, ad=ad, f=f),
        stage_id=str(pk),
        start=start,
        now=utcnow(),
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    from app.modules.crm.selectors import ad_names_for

    return column_out(found, ad_names_for(db, owner=viewer.owner, cards=found.cards))


@router.get("/cards/{pk}", responses={200: {"model": CardViewOut}})
def card(
    pk: uuid.UUID, db: Db, viewer: Viewer = Depends(card_viewer)
) -> dict[str, Any]:
    view = selectors.card_view(db, viewer=viewer, card_id=str(pk))
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return {
        "card": card_out(view.card),
        "answers": [asdict(a) for a in view.answers],
        "source": asdict(view.source) if view.source is not None else None,
        "history": [
            {
                "kind": line.kind,
                "text": line.text,
                "actor": _user(line.actor),
                "created_at": line.created_at,
            }
            for line in view.history
        ],
        "stages": [stage_out(s) for s in view.stages],
        "members": [member_out(m) for m in view.members],
        "pair": viewer.pair.key if viewer.pair is not None else None,
        "reasons": [{"id": str(r.id), "name": r.name} for r in view.reasons],
        "currency": view.currency,
        "can_work": view.can_work,
    }


def _done(db: Session, card_obj: CrmCard) -> dict[str, Any]:
    db.commit()
    db.refresh(card_obj)
    return card_out(card_obj)


class MoveIn(BaseModel):
    to: str


class TextIn(BaseModel):
    text: str = ""


class DueIn(BaseModel):
    due: datetime
    note: str = ""


class WinIn(BaseModel):
    amount: str
    note: str = ""


class LoseIn(BaseModel):
    reason: str
    note: str = ""


class AssignIn(BaseModel):
    assignee: str = ""


@router.post("/cards/{pk}/take", responses={200: {"model": CardOut}})
def take(
    pk: uuid.UUID, db: Db, viewer: Viewer = Depends(card_viewer)
) -> dict[str, Any]:
    return _done(db, services.take_card(db, viewer=viewer, card_id=str(pk)))


@router.post("/cards/{pk}/move", responses={200: {"model": CardOut}})
def move(
    pk: uuid.UUID, body: MoveIn, db: Db, viewer: Viewer = Depends(card_viewer)
) -> dict[str, Any]:
    return _done(
        db, services.move_card(db, viewer=viewer, card_id=str(pk), stage_id=body.to)
    )


@router.post("/cards/{pk}/note", responses={200: {"model": CardOut}})
def note(
    pk: uuid.UUID, body: TextIn, db: Db, viewer: Viewer = Depends(card_viewer)
) -> dict[str, Any]:
    return _done(
        db, services.note_card(db, viewer=viewer, card_id=str(pk), text=body.text)
    )


@router.post("/cards/{pk}/no-answer", responses={200: {"model": CardOut}})
def no_answer(
    pk: uuid.UUID, db: Db, viewer: Viewer = Depends(card_viewer)
) -> dict[str, Any]:
    return _done(db, services.mark_no_answer(db, viewer=viewer, card_id=str(pk)))


@router.post("/cards/{pk}/due", responses={200: {"model": CardOut}})
def due(
    pk: uuid.UUID, body: DueIn, db: Db, viewer: Viewer = Depends(card_viewer)
) -> dict[str, Any]:
    return _done(
        db,
        services.set_due(
            db, viewer=viewer, card_id=str(pk), due_at=body.due, note=body.note
        ),
    )


@router.post("/cards/{pk}/due/done", responses={200: {"model": CardOut}})
def due_done(
    pk: uuid.UUID, db: Db, viewer: Viewer = Depends(card_viewer)
) -> dict[str, Any]:
    return _done(db, services.finish_due(db, viewer=viewer, card_id=str(pk)))


@router.post("/cards/{pk}/win", responses={200: {"model": CardOut}})
def win(
    pk: uuid.UUID, body: WinIn, db: Db, viewer: Viewer = Depends(card_viewer)
) -> dict[str, Any]:
    return _done(
        db,
        services.win_card(
            db, viewer=viewer, card_id=str(pk), amount=body.amount, note=body.note
        ),
    )


@router.post("/cards/{pk}/lose", responses={200: {"model": CardOut}})
def lose(
    pk: uuid.UUID, body: LoseIn, db: Db, viewer: Viewer = Depends(card_viewer)
) -> dict[str, Any]:
    return _done(
        db,
        services.lose_card(
            db, viewer=viewer, card_id=str(pk), reason_id=body.reason, note=body.note
        ),
    )


@router.post("/cards/{pk}/assign", responses={200: {"model": CardOut}})
def assign(
    pk: uuid.UUID, body: AssignIn, db: Db, viewer: Viewer = Depends(card_owner_viewer)
) -> dict[str, Any]:
    return _done(
        db,
        services.assign_card(db, viewer=viewer, card_id=str(pk), user_id=body.assignee),
    )


@router.post("/leads/{pk}/add", responses={200: {"model": CardOut}})
def add_lead(
    pk: uuid.UUID, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> dict[str, Any]:
    return _done(db, services.add_lead(db, viewer=viewer, lead_id=str(pk)))


class PasswordIn(BaseModel):
    password: str
    again: str


@router.post("/password", responses={200: {"model": OkOut}})
def first_password(body: PasswordIn, db: Db, user: CurrentUser) -> dict[str, bool]:
    services.change_first_password(
        db, user=user, password=body.password, again=body.again
    )
    db.commit()
    return {"ok": True}


def _settings(db: Session, viewer: Viewer) -> dict[str, Any]:
    owner = viewer.owner
    setup = selectors.setup_of(db, scope=viewer.scope)
    stages = selectors.stages_of(db, scope=viewer.scope)
    return pairs_out(viewer) | {
        "setup": {
            "state": setup.state,
            "step": setup.step,
            "since": setup.since,
            "leads_since": setup.leads_since,
            "every_ad": setup.every_ad,
            "ad_external_ids": setup.ad_external_ids,
            "offered_ad_ids": setup.offered_ad_ids,
            "take_new_ads": setup.take_new_ads,
            "distribution": setup.distribution,
            "currency": setup.currency,
        }
        if setup
        else None,
        "stages": [stage_out(s) for s in stages],
        "members": team_out(db, viewer),
        "reasons": [
            {"id": str(r.id), "name": r.name}
            for r in selectors.reasons_of(db, scope=viewer.scope)
        ],
        "ads": [
            asdict(option)
            for option in selectors.lead_ads(
                db,
                owner=owner,
                pair=viewer.pair,
                since=setup.leads_since if setup else None,
            )
        ],
        "presets": [
            {
                "key": key,
                "label": PRESET_LABELS[key],
                "kind": kind,
                "color": color,
                "default": d,
                "always": a,
            }
            for key, kind, color, d, a in PRESETS
        ],
        "colors": list(COLORS),
        "custom_slots": MAX_CUSTOM_STAGES,
        "since_choices": [{"value": k, "label": v} for k, v in SINCE_LABELS.items()],
        "distribution_choices": [
            {"value": k, "label": v} for k, v in DISTRIBUTION_LABELS.items()
        ],
    }


@router.get("/settings", responses={200: {"model": SettingsOut}})
def settings_view(db: Db, viewer: Viewer = Depends(owner_viewer)) -> dict[str, Any]:
    return _settings(db, viewer)


class SetupStepIn(BaseModel):
    presets: list[str] = []
    columns: list[str] = []
    custom: dict[str, tuple[str, str]] = {}
    distribution: str = ""
    since: str = Since.WEEK
    day: date | None = None
    every_ad: bool = True
    ad: list[str] = []
    offered: list[str] = []
    take_new_ads: bool = False
    quality: list[str] = []


@router.post("/setup/{step}", responses={200: {"model": SetupStepOut}})
def setup_step(
    step: int, body: SetupStepIn, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> dict[str, Any]:
    if step not in STEPS:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    services.require_pair(viewer)
    setup = selectors.setup_of(db, scope=viewer.scope)
    if step > (setup.step if setup else 1):
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"step": setup.step if setup else 1}
        )
    placed = 0
    if step == 1:
        if not selectors.stages_of(db, scope=viewer.scope):
            columns: list[str | tuple[str, str]] = []
            ticked = set(body.presets)
            for key in body.columns:
                if key in ticked:
                    columns.append(key)
                elif key in body.custom and body.custom[key][0].strip():
                    columns.append(body.custom[key])
            services.setup_stages(db, viewer=viewer, columns=columns)
        else:
            services.advance_setup(db, viewer=viewer, to=2)
    elif step == 2:
        services.save_distribution(
            db, viewer=viewer, distribution=body.distribution, advance_to=3
        )
    elif step == 3:
        services.save_flow(
            db,
            viewer=viewer,
            since=body.since,
            day=body.day,
            every_ad=body.every_ad,
            ad_ids=body.ad,
            offered_ids=body.offered,
            take_new_ads=body.take_new_ads,
            advance_to=4,
        )
    else:
        services.save_quality(db, viewer=viewer, stage_ids=body.quality, advance_to=4)
        placed = services.enable_crm(db, viewer=viewer)
    db.commit()
    return {"next": min(step + 1, 5), "placed": placed} | _settings(db, viewer)


@router.post("/setup/skip-members", responses={200: {"model": DetailOut}})
def skip_members(db: Db, viewer: Viewer = Depends(owner_viewer)) -> dict[str, Any]:
    services.save_distribution(
        db, viewer=viewer, distribution=Distribution.MANUAL, advance_to=3
    )
    db.commit()
    return {
        "detail": "Hamma lid sizda bo'ladi. Menejerni keyin ham qo'shsangiz bo'ladi."
    }


class StateIn(BaseModel):
    state: str


@router.post("/settings/state", responses={200: {"model": PlacedOut}})
def state(
    body: StateIn, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> dict[str, Any]:
    placed = 0
    if body.state == "on":
        placed = services.enable_crm(db, viewer=viewer)
    else:
        services.disable_crm(db, viewer=viewer)
    db.commit()
    return {"placed": placed}


class StageIn(BaseModel):
    name: str = Field(max_length=48)
    color: str = ""


@router.post("/settings/stages", responses={200: {"model": StageOut}})
def stage_add(
    body: StageIn, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> dict[str, Any]:
    stage = services.add_stage(db, viewer=viewer, name=body.name, color=body.color)
    db.commit()
    return stage_out(stage)


@router.put("/settings/stages/{pk}", responses={200: {"model": StageOut}})
def stage_update(
    pk: uuid.UUID, body: StageIn, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> dict[str, Any]:
    stage = services.update_stage(
        db, viewer=viewer, stage_id=str(pk), name=body.name, color=body.color
    )
    db.commit()
    return stage_out(stage)


class StepIn(BaseModel):
    way: str = "right"


@router.post("/settings/stages/{pk}/move", responses={200: {"model": list[StageOut]}})
def stage_move(
    pk: uuid.UUID, body: StepIn, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> list[dict[str, Any]]:
    stages = services.move_stage(
        db, viewer=viewer, stage_id=str(pk), step=1 if body.way == "right" else -1
    )
    db.commit()
    return [stage_out(s) for s in stages]


@router.delete("/settings/stages/{pk}", responses={200: {"model": CardsMovedOut}})
def stage_delete(
    pk: uuid.UUID, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> dict[str, int]:
    moved = services.delete_stage(db, viewer=viewer, stage_id=str(pk))
    db.commit()
    return {"cards_moved": moved}


class MemberIn(BaseModel):
    name: str
    email: str = ""
    password: str = ""
    takes_leads: bool = True
    kpi_fix: str = ""
    kpi_percent: str = ""


@router.post(
    "/settings/members", status_code=201, responses={201: {"model": MemberOut}}
)
def member_add(
    body: MemberIn, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> dict[str, Any]:
    member = services.add_member(
        db,
        viewer=viewer,
        name=body.name,
        email=body.email,
        password=body.password,
        kpi_fix=body.kpi_fix,
        kpi_percent=body.kpi_percent,
    )
    db.commit()
    return member_out(
        member,
        seated=member.id in selectors.seated_ids(db, owner=viewer.owner, at=utcnow()),
    )


@router.put("/settings/members/{pk}", responses={200: {"model": MemberOut}})
def member_update(
    pk: uuid.UUID, body: MemberIn, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> dict[str, Any]:
    member = services.update_member(
        db,
        viewer=viewer,
        member_id=str(pk),
        name=body.name,
        takes_leads=body.takes_leads,
        kpi_fix=body.kpi_fix,
        kpi_percent=body.kpi_percent,
    )
    db.commit()
    return member_out(member)


class MemberPasswordIn(BaseModel):
    password: str


@router.post("/settings/members/{pk}/password", responses={200: {"model": MemberOut}})
def member_password(
    pk: uuid.UUID,
    body: MemberPasswordIn,
    db: Db,
    viewer: Viewer = Depends(owner_viewer),
) -> dict[str, Any]:
    member = services.reset_member_password(
        db, viewer=viewer, member_id=str(pk), password=body.password
    )
    db.commit()
    return member_out(member)


@router.delete("/settings/members/{pk}", responses={200: {"model": CardsReleasedOut}})
def member_remove(
    pk: uuid.UUID, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> dict[str, int]:
    released = services.remove_member(db, viewer=viewer, member_id=str(pk))
    db.commit()
    return {"cards_released": released}


class DistributionIn(BaseModel):
    distribution: str


@router.post("/settings/distribution", responses={200: {"model": SettingsOut}})
def distribution(
    body: DistributionIn, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> dict[str, Any]:
    services.save_distribution(db, viewer=viewer, distribution=body.distribution)
    db.commit()
    return _settings(db, viewer)


@router.post("/settings/flow", responses={200: {"model": SettingsOut}})
def flow(
    body: SetupStepIn, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> dict[str, Any]:
    services.save_flow(
        db,
        viewer=viewer,
        since=body.since,
        day=body.day,
        every_ad=body.every_ad,
        ad_ids=body.ad,
        offered_ids=body.offered,
        take_new_ads=body.take_new_ads,
    )
    db.commit()
    return _settings(db, viewer)


@router.post("/settings/quality", responses={200: {"model": SettingsOut}})
def quality(
    body: SetupStepIn, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> dict[str, Any]:
    services.save_quality(db, viewer=viewer, stage_ids=body.quality)
    db.commit()
    return _settings(db, viewer)


class ReasonIn(BaseModel):
    name: str = Field(max_length=64)


@router.post(
    "/settings/reasons", status_code=201, responses={201: {"model": ReasonOut}}
)
def reason_add(
    body: ReasonIn, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> dict[str, str]:
    reason = services.add_reason(db, viewer=viewer, name=body.name)
    db.commit()
    return {"id": str(reason.id), "name": reason.name}


@router.delete("/settings/reasons/{pk}", responses={200: {"model": OkOut}})
def reason_delete(
    pk: uuid.UUID, db: Db, viewer: Viewer = Depends(owner_viewer)
) -> dict[str, bool]:
    services.delete_reason(db, viewer=viewer, reason_id=str(pk))
    db.commit()
    return {"ok": True}
