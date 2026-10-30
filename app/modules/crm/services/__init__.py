"""Writes on the customer's own CRM board."""

import uuid
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.config import settings
from app.common.dates import date_format, localtime
from app.common.db import on_commit, utcnow
from app.common.deletion import delete_rows
from app.common.money import format_minor, to_minor
from app.common.passwords import PasswordInvalid, validate_password
from app.modules.accounts.exceptions import EmailTaken as LoginTaken
from app.modules.accounts.models import User
from app.modules.audit.constants import ActionStatus, ActionType, ActorType, EventName
from app.modules.audit.models import ActionLog
from app.modules.audit.services import emit
from app.modules.crm.constants import (
    ACTION_TARGET_PROVIDER,
    BACKFILL_LIMIT,
    CLOSING_KINDS,
    COLORS,
    DEFAULT_LOST_REASONS,
    MAX_CUSTOM_STAGES,
    MAX_MEMBERS,
    MAX_STAGES,
    PRESET_LABELS,
    PRESETS,
    SWEEP_LIMIT,
    SWEEP_WINDOW_HOURS,
    ActivityKind,
    Distribution,
    SetupState,
    Since,
    StageKind,
)
from app.modules.crm.exceptions import (
    AlreadyOnBoard,
    AlreadyTaken,
    AmountRequired,
    BadKpi,
    CrmClosed,
    DueInPast,
    EmailTaken,
    EmptyNote,
    NameRequired,
    NoAdsChosen,
    NoPair,
    NotConfigured,
    NotOnPair,
    NotRunning,
    NotYours,
    PasswordsDiffer,
    PasswordTooWeak,
    ReasonRequired,
    StageLocked,
    TooManyMembers,
    TooManyStages,
    UnknownCard,
    UnknownMember,
    UseTheDialog,
)
from app.modules.crm.models import (
    CrmActivity,
    CrmCard,
    CrmLostReason,
    CrmMember,
    CrmSetup,
    CrmStage,
)
from app.modules.crm.selectors import (
    LeadPlace,
    Scope,
    Viewer,
    countable_leads,
    crm_open,
    holds,
    is_running,
    lead_places,
    pair_of_lead,
    qualified_count,
    seated_ids,
)
from app.modules.leads.models import Lead

SPACES = (" ", "\xa0", " ", "'", "_")
GRACE = timedelta(minutes=5)
Placement = Literal["placed", "returned", "skipped", "already"]

__all__ = ["LeadPlace", "crm_open", "is_running", "lead_places", "qualified_count"]


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        return None


def read_amount(raw: str) -> Decimal | None:
    text = raw.strip()
    for space in SPACES:
        text = text.replace(space, "")
    if not text:
        return None
    if "," in text and "." in text:
        point = "," if text.rfind(",") > text.rfind(".") else "."
        text = text.replace("." if point == "," else ",", "").replace(point, ".")
    else:
        for mark in (",", "."):
            if text.count(mark) > 1 or (
                text.count(mark) == 1 and len(text.rsplit(mark, 1)[1]) == 3
            ):
                text = text.replace(mark, "")
            else:
                text = text.replace(mark, ".")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def read_fix(raw: str, *, currency: str) -> int | None:
    if not raw.strip():
        return None
    amount = read_amount(raw)
    if amount is None or amount < 0:
        raise BadKpi
    return int(to_minor(amount=amount, currency=currency))


def read_percent(raw: str) -> int | None:
    text = raw.replace("%", "").strip()
    if not text:
        return None
    if not text.isdigit() or not 0 <= int(text) <= 100:
        raise BadKpi
    return int(text)


def check_password(*, password: str, email: str, full_name: str) -> None:
    try:
        validate_password(password, email=email, full_name=full_name)
    except PasswordInvalid as exc:
        raise PasswordTooWeak(str(exc)) from exc


def require_pair(viewer: Viewer) -> Scope:
    if viewer.scope is None:
        raise NoPair
    return viewer.scope


def require_owner(viewer: Viewer) -> Scope:
    if not crm_open(owner=viewer.owner):
        raise CrmClosed
    if not viewer.is_owner:
        raise NotYours
    return require_pair(viewer)


def require_open(viewer: Viewer) -> None:
    if not crm_open(owner=viewer.owner):
        raise CrmClosed


def scope_of(row: CrmSetup | CrmCard) -> Scope:
    assert row.page_id is not None and row.ad_account_id is not None
    return Scope(
        owner_id=row.owner_id, page_id=row.page_id, ad_account_id=row.ad_account_id
    )


def setup_for_update(db: Session, *, scope: Scope) -> CrmSetup:
    setup = db.scalar(select(CrmSetup).where(scope.holds(CrmSetup)).with_for_update())
    if setup is None:
        setup = CrmSetup(**scope.fields(), currency=settings.billing_currency)
        db.add(setup)
        db.flush()
    return setup


def record_config(
    db: Session,
    *,
    owner: User,
    actor: User,
    level: str,
    target_id: uuid.UUID | str,
    before: dict[str, Any],
    after: dict[str, Any],
    event: EventName,
    now: datetime,
) -> None:
    db.add(
        ActionLog(
            owner_id=owner.id,
            actor_type=ActorType.USER,
            actor_id=actor.id,
            target_provider=ACTION_TARGET_PROVIDER,
            target_level=level,
            target_external_id=str(target_id),
            action=ActionType.CRM_CHANGE,
            request_payload=after,
            previous_state=before,
            result_payload={},
            dropped=[],
            idempotency_key=f"crm:{level}:{uuid.uuid4().hex}",
            status=ActionStatus.APPLIED,
            applied_at=now,
            dry_run=False,
        )
    )
    emit(
        db,
        owner_id=owner.id,
        name=event,
        aggregate_type=f"crm_{level}",
        aggregate_id=target_id,
        payload=after,
        occurred_at=now,
    )


def log_card(
    db: Session,
    *,
    card: CrmCard,
    actor: User | None,
    kind: ActivityKind,
    text: str = "",
    event: EventName = EventName.CRM_CARD_CHANGED,
    now: datetime,
) -> CrmActivity:
    line = CrmActivity(
        owner_id=card.owner_id,
        card_id=card.id,
        actor_id=actor.id if actor else None,
        kind=kind,
        text=text[:500],
    )
    db.add(line)
    db.flush()
    stage = db.get(CrmStage, card.stage_id)
    emit(
        db,
        owner_id=card.owner_id,
        name=event,
        aggregate_type="crm_card",
        aggregate_id=card.id,
        payload={
            "card_id": str(card.id),
            "lead_id": str(card.lead_id),
            "kind": str(kind),
            "stage": stage.name if stage else "",
            "assignee_id": str(card.assignee_id) if card.assignee_id else "",
        },
        occurred_at=now,
    )
    return line


def qualifies(*, stage: CrmStage) -> bool:
    if stage.kind in (StageKind.LOST, StageKind.NEW):
        return False
    return stage.counts_as_quality


def stage_state(stage: CrmStage) -> dict[str, Any]:
    return {
        "name": stage.name,
        "color": stage.color,
        "kind": stage.kind,
        "position": stage.position,
    }


def card_for_write(
    db: Session,
    *,
    viewer: Viewer,
    card_id: str,
    purpose: Literal["work", "take"] = "work",
) -> CrmCard:
    require_open(viewer)
    card = db.scalar(
        select(CrmCard)
        .where(holds(viewer.scope, CrmCard), CrmCard.id == _uuid(card_id))
        .with_for_update(of=CrmCard)
    )
    if card is None:
        raise UnknownCard
    if viewer.is_owner or card.assignee_id == viewer.user.id:
        return card
    if card.assignee_id is None and purpose == "take":
        return card
    raise NotYours


def _members(db: Session, scope: Scope) -> list[CrmMember]:
    return list(
        db.scalars(
            select(CrmMember)
            .where(scope.holds(CrmMember))
            .order_by(CrmMember.created_at)
        )
    )


def _takers(db: Session, scope: Scope) -> list[CrmMember]:
    """The pair's managers that sit in a seat: only they are handed leads."""
    owner = db.get(User, scope.owner_id)
    if owner is None:
        return []
    seated = seated_ids(db, owner=owner, at=utcnow())
    return [member for member in _members(db, scope) if member.id in seated]


def takes_lead(*, setup: CrmSetup, lead: Lead) -> bool:
    if setup.state != SetupState.ON or lead.is_test or lead.is_organic:
        return False
    if setup.leads_since is not None and lead.submitted_at < setup.leads_since:
        return False
    if setup.every_ad:
        return True
    ad = lead.ad_external_id
    if ad in (setup.ad_external_ids or []):
        return True
    return setup.take_new_ads and bool(ad) and ad not in (setup.offered_ad_ids or [])


def next_assignee(*, setup: CrmSetup, members: Sequence[CrmMember]) -> User | None:
    if setup.distribution != Distribution.ROUND_ROBIN:
        return None
    takers = [
        m.user for m in members if m.is_active and m.takes_leads and m.user.is_active
    ]
    if not takers:
        return None
    ids = [user.id for user in takers]
    last = setup.last_assigned_id
    if last in ids:
        return takers[(ids.index(last) + 1) % len(takers)]
    order = [member.user_id for member in members]
    if last in order:
        place = order.index(last)
        for user in takers:
            if order.index(user.id) > place:
                return user
    return takers[0]


def card_for_phone(db: Session, *, setup: CrmSetup, lead: Lead) -> CrmCard | None:
    """The card this telephone already has on the setup's pair.

    Per pair: the same person writing to two pages is a customer of each,
    and each CRM works its own card.
    """
    if not lead.phone_e164:
        return None
    return db.scalar(
        select(CrmCard)
        .join(Lead, Lead.id == CrmCard.lead_id)
        .where(scope_of(setup).holds(CrmCard), Lead.phone_e164 == lead.phone_e164)
        .order_by(CrmCard.updated_at.desc())
        .limit(1)
        .with_for_update(of=CrmCard)
    )


def is_newer(*, lead: Lead, card: CrmCard) -> bool:
    return lead.submitted_at > card.lead.submitted_at


def welcome_back(
    db: Session, *, card: CrmCard, lead: Lead, first: CrmStage, now: datetime
) -> CrmCard:
    was = card.stage
    card.lead_id = lead.id
    card.returned += 1
    if was.kind in (StageKind.WON, StageKind.LOST):
        card.stage_id = first.id
        card.closed_at = None
        card.won_amount_minor = None
        card.lost_reason_id = None
        card.lost_reason_name = ""
    db.flush()
    log_card(
        db,
        card=card,
        actor=None,
        kind=ActivityKind.RETURNED,
        text=was.name,
        event=EventName.CRM_CARD_PLACED,
        now=now,
    )
    return card


def new_card(
    db: Session,
    *,
    setup: CrmSetup,
    lead: Lead,
    first: CrmStage,
    members: Sequence[CrmMember],
    now: datetime,
) -> CrmCard:
    assignee = next_assignee(setup=setup, members=members)
    card = CrmCard(
        **scope_of(setup).fields(),
        lead_id=lead.id,
        stage_id=first.id,
        assignee_id=assignee.id if assignee else None,
        taken_at=now if assignee else None,
    )
    db.add(card)
    db.flush()
    log_card(
        db,
        card=card,
        actor=None,
        kind=ActivityKind.ARRIVED,
        event=EventName.CRM_CARD_PLACED,
        now=now,
    )
    if assignee is not None:
        setup.last_assigned_id = assignee.id
        log_card(
            db,
            card=card,
            actor=None,
            kind=ActivityKind.ASSIGNED,
            text=assignee.full_name or assignee.email,
            now=now,
        )
    return card


def _first_stage(db: Session, scope: Scope) -> CrmStage | None:
    return db.scalar(
        select(CrmStage)
        .where(scope.holds(CrmStage), CrmStage.kind == StageKind.NEW)
        .order_by(CrmStage.position)
        .limit(1)
    )


def _on_board(db: Session, lead_id: uuid.UUID) -> bool:
    return db.scalar(select(CrmCard.id).where(CrmCard.lead_id == lead_id)) is not None


def place_lead(db: Session, *, lead_id: str) -> Placement:
    lead = db.get(Lead, _uuid(lead_id))
    if lead is None:
        return "skipped"
    owner = db.get(User, lead.owner_id)
    if owner is None or not crm_open(owner=owner):
        return "skipped"
    pair = pair_of_lead(db, owner=owner, lead_id=lead.id)
    if pair is None:
        return "skipped"
    scope = Scope.of(pair)
    setup = db.scalar(
        select(CrmSetup).where(scope.holds(CrmSetup)).with_for_update(of=CrmSetup)
    )
    if setup is None or not takes_lead(setup=setup, lead=lead):
        return "skipped"
    if _on_board(db, lead.id):
        return "already"
    first = _first_stage(db, scope)
    if first is None:
        return "skipped"
    now = utcnow()
    existing = card_for_phone(db, setup=setup, lead=lead)
    if existing is not None:
        if not is_newer(lead=lead, card=existing):
            return "already"
        welcome_back(db, card=existing, lead=lead, first=first, now=now)
        db.commit()
        return "returned"
    new_card(
        db, setup=setup, lead=lead, first=first, members=_takers(db, scope), now=now
    )
    db.commit()
    return "placed"


def queue_placement(db: Session, *, lead_id: str) -> None:
    from app.modules.crm.tasks import place_lead_task

    on_commit(db, lambda: place_lead_task.delay(lead_id))


def sweep_unplaced(db: Session, *, now: datetime) -> int:
    window = now - timedelta(hours=SWEEP_WINDOW_HOURS)
    boards = db.execute(
        select(CrmSetup.owner_id, func.min(CrmSetup.enabled_at))
        .where(CrmSetup.state == SetupState.ON, CrmSetup.page_id.is_not(None))
        .group_by(CrmSetup.owner_id)
    ).all()
    landed = 0
    for owner_id, enabled_at in boards:
        since = max(window, enabled_at) if enabled_at else window
        placed = select(CrmCard.lead_id).where(CrmCard.owner_id == owner_id)
        ids = list(
            db.scalars(
                select(Lead.id)
                .where(
                    Lead.owner_id == owner_id,
                    Lead.received_at >= since,
                    Lead.is_test.is_(False),
                    Lead.is_organic.is_(False),
                    Lead.id.not_in(placed),
                )
                .order_by(Lead.received_at)
                .limit(SWEEP_LIMIT)
            )
        )
        for lead_id in ids:
            if place_lead(db, lead_id=str(lead_id)) in ("placed", "returned"):
                landed += 1
    return landed


def add_lead(db: Session, *, viewer: Viewer, lead_id: str) -> CrmCard:
    require_owner(viewer)
    owner = viewer.owner
    lead = db.scalar(
        select(Lead).where(Lead.owner_id == owner.id, Lead.id == _uuid(lead_id))
    )
    if lead is None:
        raise UnknownCard
    pair = pair_of_lead(db, owner=owner, lead_id=lead.id)
    if pair is None:
        raise NotOnPair
    scope = Scope.of(pair)
    setup = setup_for_update(db, scope=scope)
    if setup.state != SetupState.ON:
        raise NotRunning
    if _on_board(db, lead.id):
        raise AlreadyOnBoard
    first = _first_stage(db, scope)
    if first is None:
        raise NotConfigured
    now = utcnow()
    existing = card_for_phone(db, setup=setup, lead=lead)
    if existing is not None:
        if not is_newer(lead=lead, card=existing):
            raise AlreadyOnBoard
        return welcome_back(db, card=existing, lead=lead, first=first, now=now)
    return new_card(
        db, setup=setup, lead=lead, first=first, members=_takers(db, scope), now=now
    )


def add_member(
    db: Session,
    *,
    viewer: Viewer,
    name: str,
    email: str,
    password: str,
    kpi_fix: str = "",
    kpi_percent: str = "",
) -> CrmMember:
    from app.modules.accounts.services import create_member_login

    scope = require_owner(viewer)
    owner = viewer.owner
    setup = setup_for_update(db, scope=scope)
    name = name.strip()
    if not name:
        raise NameRequired
    check_password(password=password, email=email.strip().lower(), full_name=name)
    active = db.scalar(
        select(func.count(CrmMember.id)).where(
            scope.holds(CrmMember), CrmMember.is_active.is_(True)
        )
    )
    if (active or 0) >= MAX_MEMBERS:
        raise TooManyMembers
    fix = read_fix(kpi_fix, currency=setup.currency)
    percent = read_percent(kpi_percent)
    try:
        user = create_member_login(
            db, owner=owner, email=email, full_name=name, password=password
        )
    except LoginTaken as exc:
        raise EmailTaken from exc
    member = CrmMember(
        **scope.fields(),
        user_id=user.id,
        kpi_fix_minor=fix,
        kpi_percent=percent,
        kpi_currency=setup.currency if fix is not None else "",
    )
    db.add(member)
    db.flush()
    record_config(
        db,
        owner=owner,
        actor=viewer.user,
        level="member",
        target_id=member.id,
        before={},
        after={"email": user.email, "name": name, "kpi": member.has_kpi},
        event=EventName.CRM_MEMBER_SAVED,
        now=utcnow(),
    )
    return member


def _member(
    db: Session, *, viewer: Viewer, member_id: str, active: bool = True
) -> CrmMember:
    query = select(CrmMember).where(
        holds(viewer.scope, CrmMember), CrmMember.id == _uuid(member_id)
    )
    if active:
        query = query.where(CrmMember.is_active.is_(True))
    member = db.scalar(query)
    if member is None:
        raise UnknownMember
    return member


def update_member(
    db: Session,
    *,
    viewer: Viewer,
    member_id: str,
    name: str,
    takes_leads: bool,
    kpi_fix: str,
    kpi_percent: str,
) -> CrmMember:
    from app.modules.accounts.services import rename_member_login

    scope = require_owner(viewer)
    setup = setup_for_update(db, scope=scope)
    member = _member(db, viewer=viewer, member_id=member_id)
    if not name.strip():
        raise NameRequired

    def state() -> dict[str, object]:
        return {
            "name": member.user.full_name,
            "takes_leads": member.takes_leads,
            "kpi_fix_minor": member.kpi_fix_minor,
            "kpi_percent": member.kpi_percent,
        }

    before = state()
    fix = read_fix(kpi_fix, currency=setup.currency)
    member.kpi_fix_minor = fix
    member.kpi_percent = read_percent(kpi_percent)
    member.kpi_currency = setup.currency if fix is not None else ""
    member.takes_leads = takes_leads
    rename_member_login(db, user=member.user, full_name=name)
    record_config(
        db,
        owner=viewer.owner,
        actor=viewer.user,
        level="member",
        target_id=member.id,
        before=before,
        after=state(),
        event=EventName.CRM_MEMBER_SAVED,
        now=utcnow(),
    )
    return member


def remove_member(db: Session, *, viewer: Viewer, member_id: str) -> int:
    from app.modules.accounts.services import remove_member_login

    scope = require_owner(viewer)
    owner = viewer.owner
    setup = setup_for_update(db, scope=scope)
    member = _member(db, viewer=viewer, member_id=member_id, active=False)
    now = utcnow()
    holder = member.user
    # Every pair's: cards copied from the one-CRM days may sit on another.
    cards = list(
        db.scalars(
            select(CrmCard).where(
                CrmCard.owner_id == owner.id,
                CrmCard.page_id.is_not(None),
                CrmCard.assignee_id == holder.id,
                CrmCard.closed_at.is_(None),
            )
        )
    )
    released = 0
    name = holder.full_name or holder.email
    firsts: dict[Scope, CrmStage | None] = {}
    for card in cards:
        where = scope_of(card)
        if where not in firsts:
            firsts[where] = _first_stage(db, where)
        first = firsts[where]
        if first is None:
            continue
        if card.stage_id != first.id:
            db.add(
                CrmActivity(
                    owner_id=owner.id,
                    card_id=card.id,
                    actor_id=viewer.user.id,
                    kind=ActivityKind.MOVED,
                    text=f"{card.stage.name} → {first.name} ({name})",
                )
            )
        card.assignee_id = None
        card.stage_id = first.id
        card.taken_at = None
        card.updated_at = now
        released += 1
    if setup.last_assigned_id == member.user_id:
        team = _members(db, scope)
        order = [m.user_id for m in team]
        takers = [
            m.user
            for m in team
            if m.is_active and m.takes_leads and m.user_id != holder.id
        ]
        place = order.index(holder.id) if holder.id in order else -1
        before = [taker for taker in takers if order.index(taker.id) < place]
        chosen = before[-1] if before else (takers[-1] if takers else None)
        setup.last_assigned_id = chosen.id if chosen else None
    email = holder.email
    member_pk = member.id
    member.is_active = False
    db.flush()
    remove_member_login(db, user=holder)
    record_config(
        db,
        owner=owner,
        actor=viewer.user,
        level="member",
        target_id=member_pk,
        before={"email": email},
        after={"removed": True, "cards_released": released},
        event=EventName.CRM_MEMBER_REMOVED,
        now=now,
    )
    return released


def reset_member_password(
    db: Session, *, viewer: Viewer, member_id: str, password: str
) -> CrmMember:
    from app.modules.accounts.services import set_member_password

    require_owner(viewer)
    member = _member(db, viewer=viewer, member_id=member_id)
    check_password(
        password=password, email=member.user.email, full_name=member.user.full_name
    )
    set_member_password(db, user=member.user, password=password)
    # The owner resetting a manager's password ends the manager's sessions:
    # it is how a login somebody else learnt stops working.
    subject = str(member.user_id)
    on_commit(db, lambda: tokens.revoke_all(subject=subject, now=utcnow()))
    member.must_change_password = True
    record_config(
        db,
        owner=viewer.owner,
        actor=viewer.user,
        level="member",
        target_id=member.id,
        before={},
        after={"password_reset": True},
        event=EventName.CRM_MEMBER_SAVED,
        now=utcnow(),
    )
    return member


def change_first_password(
    db: Session, *, user: User, password: str, again: str
) -> CrmMember:
    from app.modules.accounts.services import set_member_password

    member = db.scalar(
        select(CrmMember).where(
            CrmMember.user_id == user.id, CrmMember.is_active.is_(True)
        )
    )
    if member is None:
        raise UnknownMember
    check_password(password=password, email=user.email, full_name=user.full_name)
    if password != again:
        raise PasswordsDiffer
    set_member_password(db, user=user, password=password)
    member.must_change_password = False
    db.flush()
    return member


def _stage(
    db: Session, *, viewer: Viewer, stage_id: str, lock: bool = False
) -> CrmStage:
    query = select(CrmStage).where(
        holds(viewer.scope, CrmStage), CrmStage.id == _uuid(stage_id)
    )
    if lock:
        query = query.with_for_update()
    stage = db.scalar(query)
    if stage is None:
        raise NotConfigured
    return stage


def add_stage(db: Session, *, viewer: Viewer, name: str, color: str) -> CrmStage:
    scope = require_owner(viewer)
    owner = viewer.owner
    setup_for_update(db, scope=scope)
    name = name.strip()[:48]
    if not name:
        raise NameRequired
    count = db.scalar(select(func.count(CrmStage.id)).where(scope.holds(CrmStage)))
    if (count or 0) >= MAX_STAGES:
        raise TooManyStages
    won = db.scalar(
        select(CrmStage).where(scope.holds(CrmStage), CrmStage.kind == StageKind.WON)
    )
    if won is None:
        raise NotConfigured
    position = won.position
    db.execute(
        update(CrmStage)
        .where(scope.holds(CrmStage), CrmStage.position >= position)
        .values(position=CrmStage.position + 1)
    )
    stage = CrmStage(
        **scope.fields(),
        name=name,
        color=color if color in COLORS else COLORS[0],
        kind=StageKind.OPEN,
        position=position,
        counts_as_quality=False,
    )
    db.add(stage)
    db.flush()
    record_config(
        db,
        owner=owner,
        actor=viewer.user,
        level="stage",
        target_id=stage.id,
        before={},
        after=stage_state(stage),
        event=EventName.CRM_SETUP_SAVED,
        now=utcnow(),
    )
    return stage


def update_stage(
    db: Session, *, viewer: Viewer, stage_id: str, name: str, color: str
) -> CrmStage:
    require_owner(viewer)
    stage = _stage(db, viewer=viewer, stage_id=stage_id, lock=True)
    name = name.strip()[:48]
    if not name:
        raise NameRequired
    before = stage_state(stage)
    stage.name = name
    if color in COLORS:
        stage.color = color
    db.flush()
    record_config(
        db,
        owner=viewer.owner,
        actor=viewer.user,
        level="stage",
        target_id=stage.id,
        before=before,
        after=stage_state(stage),
        event=EventName.CRM_SETUP_SAVED,
        now=utcnow(),
    )
    return stage


def delete_stage(db: Session, *, viewer: Viewer, stage_id: str) -> int:
    scope = require_owner(viewer)
    owner = viewer.owner
    setup_for_update(db, scope=scope)
    stage = _stage(db, viewer=viewer, stage_id=stage_id)
    if stage.kind != StageKind.OPEN:
        raise StageLocked
    first = _first_stage(db, scope)
    if first is None:
        raise NotConfigured
    moved = db.execute(
        update(CrmCard)
        .where(CrmCard.owner_id == owner.id, CrmCard.stage_id == stage.id)
        .values(stage_id=first.id, updated_at=utcnow())
    ).rowcount
    before = stage_state(stage)
    db.delete(stage)
    db.flush()
    record_config(
        db,
        owner=owner,
        actor=viewer.user,
        level="stage",
        target_id=stage_id,
        before=before,
        after={"deleted": True, "cards_moved": moved},
        event=EventName.CRM_SETUP_SAVED,
        now=utcnow(),
    )
    return int(moved)


def move_stage(
    db: Session, *, viewer: Viewer, stage_id: str, step: int
) -> list[CrmStage]:
    scope = require_owner(viewer)
    stages = list(
        db.scalars(
            select(CrmStage)
            .where(scope.holds(CrmStage))
            .order_by(CrmStage.position)
            .with_for_update()
        )
    )
    index = next((i for i, s in enumerate(stages) if str(s.id) == str(stage_id)), None)
    if index is None:
        raise NotConfigured
    other = index + (1 if step > 0 else -1)
    if (
        stages[index].kind != StageKind.OPEN
        or not 0 <= other < len(stages)
        or stages[other].kind != StageKind.OPEN
    ):
        raise StageLocked
    stages[index], stages[other] = stages[other], stages[index]
    for position, stage in enumerate(stages):
        stage.position = position
    db.flush()
    record_config(
        db,
        owner=viewer.owner,
        actor=viewer.user,
        level="stage",
        target_id=stage_id,
        before={"position": index},
        after={"position": other},
        event=EventName.CRM_SETUP_SAVED,
        now=utcnow(),
    )
    return stages


def setup_stages(
    db: Session, *, viewer: Viewer, columns: Sequence[str | tuple[str, str]]
) -> list[CrmStage]:
    scope = require_owner(viewer)
    owner = viewer.owner
    now = utcnow()
    setup = setup_for_update(db, scope=scope)
    existing = list(
        db.scalars(
            select(CrmStage).where(scope.holds(CrmStage)).order_by(CrmStage.position)
        )
    )
    if existing:
        return existing
    rows: list[CrmStage] = []
    closing: list[CrmStage] = []
    for preset, kind, color, _default, always in PRESETS:
        if always:
            row = CrmStage(
                **scope.fields(),
                name=str(PRESET_LABELS[preset]),
                color=color,
                kind=kind,
                counts_as_quality=False,
            )
            (closing if kind in (StageKind.WON, StageKind.LOST) else rows).append(row)
    ready = {preset: (kind, color) for preset, kind, color, _d, _a in PRESETS}
    custom = 0
    for column in columns:
        if isinstance(column, str):
            kind, color = ready.get(column, ("", ""))
            if kind != StageKind.OPEN:
                continue
            name = str(PRESET_LABELS[column])
        else:
            custom += 1
            if custom > MAX_CUSTOM_STAGES:
                continue
            name, color = column[0].strip()[:48], column[1]
            if not name:
                raise NameRequired
            color = color if color in COLORS else COLORS[0]
        rows.append(
            CrmStage(
                **scope.fields(),
                name=name,
                color=color,
                kind=StageKind.OPEN,
                counts_as_quality=False,
            )
        )
    rows += closing
    for position, row in enumerate(rows):
        row.position = position
        db.add(row)
    if not db.scalar(select(CrmLostReason.id).where(scope.holds(CrmLostReason))):
        for position, name in enumerate(DEFAULT_LOST_REASONS):
            db.add(CrmLostReason(**scope.fields(), name=str(name), position=position))
    setup.step = max(setup.step, 2)
    db.flush()
    record_config(
        db,
        owner=owner,
        actor=viewer.user,
        level="stages",
        target_id=setup.id,
        before={},
        after={"stages": [row.name for row in rows]},
        event=EventName.CRM_SETUP_SAVED,
        now=now,
    )
    return rows


def advance_setup(db: Session, *, viewer: Viewer, to: int) -> CrmSetup:
    scope = require_owner(viewer)
    setup = setup_for_update(db, scope=scope)
    if to > setup.step:
        setup.step = to
    db.flush()
    return setup


def since_moment(*, since: str, day: date | None, now: datetime) -> datetime | None:
    local = localtime(now)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if since == Since.YESTERDAY:
        return midnight - timedelta(days=1)
    if since == Since.WEEK:
        return midnight - timedelta(days=local.weekday())
    if since == Since.MONTH:
        return midnight.replace(day=1)
    if since == Since.DATE and day is not None:
        return datetime.combine(day, time.min, tzinfo=local.tzinfo)
    return None


def save_flow(
    db: Session,
    *,
    viewer: Viewer,
    since: str,
    day: date | None,
    every_ad: bool,
    ad_ids: list[str],
    offered_ids: list[str],
    take_new_ads: bool,
    advance_to: int = 0,
) -> CrmSetup:
    scope = require_owner(viewer)
    if not (every_ad or ad_ids or take_new_ads):
        raise NoAdsChosen
    now = utcnow()
    setup = setup_for_update(db, scope=scope)
    before = {
        "since": setup.since,
        "every_ad": setup.every_ad,
        "ad_external_ids": setup.ad_external_ids,
    }
    setup.since = since if since in {item.value for item in Since} else Since.WEEK
    setup.leads_since = since_moment(since=setup.since, day=day, now=now)
    if setup.since == Since.DATE and day is None:
        setup.since = Since.ONLY_NEW
    setup.every_ad = every_ad
    setup.ad_external_ids = [] if every_ad else sorted(set(ad_ids))
    setup.offered_ad_ids = sorted(set(offered_ids))
    setup.take_new_ads = take_new_ads
    setup.step = max(setup.step, advance_to)
    db.flush()
    record_config(
        db,
        owner=viewer.owner,
        actor=viewer.user,
        level="setup",
        target_id=setup.id,
        before=before,
        after={
            "since": setup.since,
            "leads_since": setup.leads_since.isoformat() if setup.leads_since else "",
            "every_ad": setup.every_ad,
            "ad_external_ids": setup.ad_external_ids,
            "take_new_ads": setup.take_new_ads,
        },
        event=EventName.CRM_SETUP_SAVED,
        now=now,
    )
    return setup


def save_distribution(
    db: Session, *, viewer: Viewer, distribution: str, advance_to: int = 0
) -> CrmSetup:
    scope = require_owner(viewer)
    setup = setup_for_update(db, scope=scope)
    before = {"distribution": setup.distribution}
    if distribution in {item.value for item in Distribution}:
        setup.distribution = distribution
    setup.step = max(setup.step, advance_to)
    db.flush()
    record_config(
        db,
        owner=viewer.owner,
        actor=viewer.user,
        level="setup",
        target_id=setup.id,
        before=before,
        after={"distribution": setup.distribution},
        event=EventName.CRM_SETUP_SAVED,
        now=utcnow(),
    )
    return setup


def save_quality(
    db: Session, *, viewer: Viewer, stage_ids: list[str], advance_to: int = 0
) -> CrmSetup:
    scope = require_owner(viewer)
    setup = setup_for_update(db, scope=scope)
    now = utcnow()
    mine = scope.holds(CrmStage)
    before = sorted(
        str(pk)
        for pk in db.scalars(
            select(CrmStage.id).where(mine, CrmStage.counts_as_quality.is_(True))
        )
    )
    wanted = [key for key in (_uuid(s) for s in stage_ids) if key]
    after = sorted(
        str(pk)
        for pk in db.scalars(
            select(CrmStage.id).where(
                mine,
                CrmStage.id.in_(wanted),
                CrmStage.kind.in_([StageKind.OPEN, StageKind.WON]),
            )
        )
    )
    chosen = [uuid.UUID(pk) for pk in after]
    db.execute(
        update(CrmStage)
        .where(mine, CrmStage.id.not_in(chosen), CrmStage.counts_as_quality.is_(True))
        .values(counts_as_quality=False, updated_at=now)
    )
    db.execute(
        update(CrmStage)
        .where(mine, CrmStage.id.in_(chosen), CrmStage.counts_as_quality.is_(False))
        .values(counts_as_quality=True, updated_at=now)
    )
    setup.step = max(setup.step, advance_to)
    db.flush()
    record_config(
        db,
        owner=viewer.owner,
        actor=viewer.user,
        level="setup",
        target_id=setup.id,
        before={"quality_stages": before},
        after={"quality_stages": after},
        event=EventName.CRM_SETUP_SAVED,
        now=now,
    )
    return setup


def enable_crm(db: Session, *, viewer: Viewer) -> int:
    scope = require_owner(viewer)
    owner = viewer.owner
    now = utcnow()
    setup = setup_for_update(db, scope=scope)
    first = _first_stage(db, scope)
    if first is None:
        raise NotConfigured
    before = {"state": setup.state}
    setup.state = SetupState.ON
    if setup.leads_since is None:
        setup.leads_since = now
    setup.enabled_at = now
    setup.step = max(setup.step, 5)
    db.flush()
    cards = {
        card.lead.phone_e164: card
        for card in db.scalars(
            select(CrmCard)
            .join(Lead, Lead.id == CrmCard.lead_id)
            .where(scope.holds(CrmCard), Lead.phone_e164 != "")
            .order_by(CrmCard.updated_at)
        )
    }
    placed_ids = select(CrmCard.lead_id).where(CrmCard.owner_id == owner.id)
    chosen: list[Lead] = []
    returning: dict[str, Lead] = {}
    seen: set[str] = set()
    for lead in db.scalars(
        countable_leads(db, owner=owner, pair=viewer.pair)
        .where(Lead.submitted_at >= setup.leads_since, Lead.id.not_in(placed_ids))
        .order_by(Lead.submitted_at.desc())
        .execution_options(yield_per=500)
    ):
        if len(chosen) >= BACKFILL_LIMIT:
            break
        phone = lead.phone_e164
        if not takes_lead(setup=setup, lead=lead) or phone in seen:
            continue
        if phone and phone in cards:
            if phone not in returning and is_newer(lead=lead, card=cards[phone]):
                returning[phone] = lead
            continue
        if phone:
            seen.add(phone)
        chosen.append(lead)
    chosen.reverse()
    for phone, lead in returning.items():
        welcome_back(db, card=cards[phone], lead=lead, first=first, now=now)
    members = _takers(db, scope)
    for lead in chosen:
        assignee = next_assignee(setup=setup, members=members)
        if assignee is not None:
            setup.last_assigned_id = assignee.id
        card = CrmCard(
            **scope.fields(),
            lead_id=lead.id,
            stage_id=first.id,
            assignee_id=assignee.id if assignee else None,
            taken_at=now if assignee else None,
        )
        db.add(card)
        db.flush()
        db.add(
            CrmActivity(
                owner_id=owner.id, card_id=card.id, kind=ActivityKind.ARRIVED, text=""
            )
        )
        if assignee is not None:
            db.add(
                CrmActivity(
                    owner_id=owner.id,
                    card_id=card.id,
                    kind=ActivityKind.ASSIGNED,
                    text=assignee.full_name or assignee.email,
                )
            )
    db.flush()
    record_config(
        db,
        owner=owner,
        actor=viewer.user,
        level="setup",
        target_id=setup.id,
        before=before,
        after={
            "state": SetupState.ON,
            "placed": len(chosen),
            "returned": len(returning),
        },
        event=EventName.CRM_ENABLED,
        now=now,
    )
    return len(chosen) + len(returning)


def disable_crm(db: Session, *, viewer: Viewer) -> CrmSetup:
    scope = require_owner(viewer)
    now = utcnow()
    setup = setup_for_update(db, scope=scope)
    before = {"state": setup.state}
    setup.state = SetupState.OFF
    setup.disabled_at = now
    db.flush()
    record_config(
        db,
        owner=viewer.owner,
        actor=viewer.user,
        level="setup",
        target_id=setup.id,
        before=before,
        after={"state": SetupState.OFF},
        event=EventName.CRM_DISABLED,
        now=now,
    )
    return setup


def add_reason(db: Session, *, viewer: Viewer, name: str) -> CrmLostReason:
    scope = require_owner(viewer)
    setup = setup_for_update(db, scope=scope)
    name = name.strip()[:64]
    if not name:
        raise NameRequired
    last = db.scalar(
        select(func.max(CrmLostReason.position)).where(scope.holds(CrmLostReason))
    )
    reason = CrmLostReason(**scope.fields(), name=name, position=(last or 0) + 1)
    db.add(reason)
    db.flush()
    record_config(
        db,
        owner=viewer.owner,
        actor=viewer.user,
        level="reason",
        target_id=setup.id,
        before={},
        after={"name": name},
        event=EventName.CRM_SETUP_SAVED,
        now=utcnow(),
    )
    return reason


def delete_reason(db: Session, *, viewer: Viewer, reason_id: str) -> None:
    scope = require_owner(viewer)
    setup = setup_for_update(db, scope=scope)
    reason = db.scalar(
        select(CrmLostReason).where(
            scope.holds(CrmLostReason), CrmLostReason.id == _uuid(reason_id)
        )
    )
    if reason is None:
        raise NotConfigured
    name = reason.name
    delete_rows(db, CrmLostReason.__table__, CrmLostReason.id == reason.id)
    db.expunge(reason)
    record_config(
        db,
        owner=viewer.owner,
        actor=viewer.user,
        level="reason",
        target_id=setup.id,
        before={"name": name},
        after={"deleted": True},
        event=EventName.CRM_SETUP_SAVED,
        now=utcnow(),
    )


def assign_card(db: Session, *, viewer: Viewer, card_id: str, user_id: str) -> CrmCard:
    if not viewer.is_owner:
        raise NotYours
    card = card_for_write(db, viewer=viewer, card_id=card_id)
    if not user_id:
        assignee = None
    elif user_id == str(viewer.owner.id):
        assignee = viewer.owner
    else:
        member = db.scalar(
            select(CrmMember).where(
                holds(viewer.scope, CrmMember),
                CrmMember.user_id == _uuid(user_id),
                CrmMember.is_active.is_(True),
            )
        )
        if member is None:
            raise UnknownMember
        assignee = member.user
    if card.assignee_id == (assignee.id if assignee else None):
        return card
    now = utcnow()
    card.assignee_id = assignee.id if assignee else None
    card.taken_at = now if assignee else None
    db.flush()
    name = (assignee.full_name or assignee.email) if assignee else ""
    log_card(
        db, card=card, actor=viewer.user, kind=ActivityKind.ASSIGNED, text=name, now=now
    )
    return card


def _closing_stage(db: Session, *, viewer: Viewer, kind: str) -> CrmStage:
    stage = db.scalar(
        select(CrmStage).where(holds(viewer.scope, CrmStage), CrmStage.kind == kind)
    )
    if stage is None:
        raise NotConfigured
    return stage


def win_card(
    db: Session, *, viewer: Viewer, card_id: str, amount: str, note: str
) -> CrmCard:
    card = card_for_write(db, viewer=viewer, card_id=card_id, purpose="take")
    setup = db.scalar(select(CrmSetup).where(scope_of(card).holds(CrmSetup)))
    currency = setup.currency if setup else ""
    value = read_amount(amount)
    if value is None or value <= 0:
        raise AmountRequired
    minor = int(to_minor(amount=value, currency=currency))
    stage = _closing_stage(db, viewer=viewer, kind=StageKind.WON)
    now = utcnow()
    card.stage_id = stage.id
    card.assignee_id = card.assignee_id or viewer.user.id
    card.won_amount_minor = minor
    card.currency = currency
    card.lost_reason_id = None
    card.lost_reason_name = ""
    card.closed_at = now
    card.due_at = None
    card.due_note = ""
    if note.strip():
        card.last_note = note.strip()[:300]
        card.last_note_at = now
    became_qualified = card.qualified_at is None and qualifies(stage=stage)
    if became_qualified:
        card.qualified_at = now
    db.flush()
    if became_qualified:
        log_card(db, card=card, actor=viewer.user, kind=ActivityKind.QUALIFIED, now=now)
    text = format_minor(amount_minor=minor, currency=currency)
    if note.strip():
        text = f"{text} · {note.strip()}"
    log_card(
        db,
        card=card,
        actor=viewer.user,
        kind=ActivityKind.WON,
        text=text,
        event=EventName.CRM_CARD_WON,
        now=now,
    )
    return card


def lose_card(
    db: Session, *, viewer: Viewer, card_id: str, reason_id: str, note: str
) -> CrmCard:
    card = card_for_write(db, viewer=viewer, card_id=card_id, purpose="take")
    reason = (
        db.scalar(
            select(CrmLostReason).where(
                holds(viewer.scope, CrmLostReason),
                CrmLostReason.id == _uuid(reason_id),
            )
        )
        if reason_id
        else None
    )
    if reason is None:
        raise ReasonRequired
    stage = _closing_stage(db, viewer=viewer, kind=StageKind.LOST)
    now = utcnow()
    card.stage_id = stage.id
    card.assignee_id = card.assignee_id or viewer.user.id
    card.lost_reason_id = reason.id
    card.lost_reason_name = reason.name
    card.won_amount_minor = None
    card.closed_at = now
    card.due_at = None
    card.due_note = ""
    if note.strip():
        card.last_note = note.strip()[:300]
        card.last_note_at = now
    db.flush()
    text = f"{reason.name} · {note.strip()}" if note.strip() else reason.name
    log_card(
        db,
        card=card,
        actor=viewer.user,
        kind=ActivityKind.LOST,
        text=text,
        event=EventName.CRM_CARD_LOST,
        now=now,
    )
    return card


def set_due(
    db: Session, *, viewer: Viewer, card_id: str, due_at: datetime, note: str
) -> CrmCard:
    card = card_for_write(db, viewer=viewer, card_id=card_id)
    now = utcnow()
    if due_at < now - GRACE:
        raise DueInPast
    card.due_at = due_at
    card.due_note = note.strip()[:200]
    db.flush()
    when = date_format(localtime(due_at), "d.m.Y H:i")
    text = f"{when} · {card.due_note}" if card.due_note else when
    log_card(
        db, card=card, actor=viewer.user, kind=ActivityKind.DUE_SET, text=text, now=now
    )
    return card


def finish_due(db: Session, *, viewer: Viewer, card_id: str) -> CrmCard:
    card = card_for_write(db, viewer=viewer, card_id=card_id)
    if card.due_at is None:
        return card
    now = utcnow()
    text = card.due_note
    card.due_at = None
    card.due_note = ""
    db.flush()
    log_card(
        db, card=card, actor=viewer.user, kind=ActivityKind.DUE_DONE, text=text, now=now
    )
    return card


def move_card(db: Session, *, viewer: Viewer, card_id: str, stage_id: str) -> CrmCard:
    card = card_for_write(db, viewer=viewer, card_id=card_id, purpose="take")
    target = _stage(db, viewer=viewer, stage_id=stage_id)
    if target.kind in CLOSING_KINDS:
        raise UseTheDialog
    if target.id == card.stage_id:
        return card
    now = utcnow()
    was = card.stage
    if was.kind in CLOSING_KINDS:
        card.closed_at = None
        card.won_amount_minor = None
        card.lost_reason_id = None
        card.lost_reason_name = ""
        log_card(
            db,
            card=card,
            actor=viewer.user,
            kind=ActivityKind.REOPENED,
            text=was.name,
            now=now,
        )
    if card.assignee_id is None and (
        not viewer.is_owner or target.kind != StageKind.NEW
    ):
        card.assignee_id = viewer.user.id
        card.taken_at = now
    card.stage_id = target.id
    became_qualified = card.qualified_at is None and qualifies(stage=target)
    if became_qualified:
        card.qualified_at = now
    db.flush()
    log_card(
        db,
        card=card,
        actor=viewer.user,
        kind=ActivityKind.MOVED,
        text=f"{was.name} → {target.name}",
        now=now,
    )
    if became_qualified:
        log_card(db, card=card, actor=viewer.user, kind=ActivityKind.QUALIFIED, now=now)
    return card


def note_card(db: Session, *, viewer: Viewer, card_id: str, text: str) -> CrmCard:
    card = card_for_write(db, viewer=viewer, card_id=card_id)
    text = text.strip()
    if not text:
        raise EmptyNote
    now = utcnow()
    card.last_note = text[:300]
    card.last_note_at = now
    db.flush()
    log_card(
        db, card=card, actor=viewer.user, kind=ActivityKind.NOTE, text=text, now=now
    )
    return card


def mark_no_answer(db: Session, *, viewer: Viewer, card_id: str) -> CrmCard:
    card = card_for_write(db, viewer=viewer, card_id=card_id)
    now = utcnow()
    card.attempts += 1
    db.flush()
    log_card(
        db,
        card=card,
        actor=viewer.user,
        kind=ActivityKind.NO_ANSWER,
        text=str(card.attempts),
        now=now,
    )
    return card


def take_card(db: Session, *, viewer: Viewer, card_id: str) -> CrmCard:
    card = card_for_write(db, viewer=viewer, card_id=card_id, purpose="take")
    if card.assignee_id is not None and card.assignee_id != viewer.user.id:
        raise AlreadyTaken
    now = utcnow()
    card.assignee_id = viewer.user.id
    card.taken_at = card.taken_at or now
    became_qualified = False
    if card.stage.kind == StageKind.NEW:
        working = db.scalar(
            select(CrmStage)
            .where(holds(viewer.scope, CrmStage), CrmStage.kind == StageKind.OPEN)
            .order_by(CrmStage.position)
            .limit(1)
        )
        if working is not None:
            card.stage_id = working.id
            if card.qualified_at is None and qualifies(stage=working):
                card.qualified_at = now
                became_qualified = True
    db.flush()
    db.refresh(card)
    log_card(
        db,
        card=card,
        actor=viewer.user,
        kind=ActivityKind.TAKEN,
        text=card.stage.name,
        now=now,
    )
    if became_qualified:
        log_card(db, card=card, actor=viewer.user, kind=ActivityKind.QUALIFIED, now=now)
    return card
