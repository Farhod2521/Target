import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.modules.accounts.models import User
from app.modules.crm.constants import (
    CARDS_PER_COLUMN,
    CLOSED_DAYS_ON_BOARD,
    LOST_REASONS_SHOWN,
    Flag,
    SetupState,
    StageKind,
)
from app.modules.crm.models import (
    CrmActivity,
    CrmCard,
    CrmLostReason,
    CrmMember,
    CrmSetup,
    CrmStage,
)
from app.modules.leads.models import Lead, LeadForm

HISTORY_SHOWN = 40
CONTACT_KEYS = frozenset({"full_name", "phone_number", "email", "city"})


@dataclass(frozen=True, slots=True)
class Viewer:
    owner: User
    user: User
    member: CrmMember | None

    @property
    def is_owner(self) -> bool:
        return self.member is None and self.user.id == self.owner.id

    @property
    def may_work(self) -> bool:
        if self.is_owner:
            return True
        return (
            self.member is not None
            and self.member.is_active
            and bool(self.owner.is_active)
        )


def viewer_for(db: Session, *, user: User) -> Viewer:
    if user.crm_owner_id is None:
        return Viewer(owner=user, user=user, member=None)
    member = db.scalar(select(CrmMember).where(CrmMember.user_id == user.id))
    owner_id = member.owner_id if member is not None else user.crm_owner_id
    owner = db.get(User, owner_id) or user
    return Viewer(owner=owner, user=user, member=member)


def crm_open(db: Session | None = None, *, owner: User) -> bool:
    return bool(owner.is_staff)


def setup_of(db: Session, *, owner: User) -> CrmSetup | None:
    return db.scalar(select(CrmSetup).where(CrmSetup.owner_id == owner.id))


def is_running(db: Session, *, owner: User) -> bool:
    return (
        db.scalar(
            select(CrmSetup.id).where(
                CrmSetup.owner_id == owner.id, CrmSetup.state == SetupState.ON
            )
        )
        is not None
    )


def stages_of(db: Session, *, owner: User) -> list[CrmStage]:
    return list(
        db.scalars(
            select(CrmStage)
            .where(CrmStage.owner_id == owner.id)
            .order_by(CrmStage.position, CrmStage.created_at)
        )
    )


def stage_of_kind(db: Session, *, owner: User, kind: str) -> CrmStage | None:
    return db.scalar(
        select(CrmStage)
        .where(CrmStage.owner_id == owner.id, CrmStage.kind == kind)
        .order_by(CrmStage.position)
        .limit(1)
    )


def members_of(db: Session, *, owner: User) -> list[CrmMember]:
    return list(
        db.scalars(
            select(CrmMember)
            .where(CrmMember.owner_id == owner.id)
            .order_by(CrmMember.created_at)
        )
    )


def active_members(db: Session, *, owner: User) -> list[CrmMember]:
    return [member for member in members_of(db, owner=owner) if member.is_active]


def reasons_of(db: Session, *, owner: User) -> list[CrmLostReason]:
    return list(
        db.scalars(
            select(CrmLostReason)
            .where(CrmLostReason.owner_id == owner.id)
            .order_by(CrmLostReason.position, CrmLostReason.created_at)
        )
    )


@dataclass(frozen=True, slots=True)
class AdOption:
    external_id: str
    title: str
    form_name: str
    leads: int


def countable_leads(db: Session, *, owner: User) -> Select[tuple[Lead]]:
    from app.modules.leads.selectors import subscribed_lead_scope

    return select(Lead).where(
        Lead.owner_id == owner.id,
        Lead.is_test.is_(False),
        Lead.is_organic.is_(False),
        subscribed_lead_scope(db, owner=owner),
    )


def lead_ads(db: Session, *, owner: User, since: datetime | None) -> list[AdOption]:
    from app.modules.ads.constants import Delivery
    from app.modules.ads.models import Ad

    ads = list(
        db.scalars(
            select(Ad)
            .where(
                Ad.owner_id == owner.id,
                Ad.delivery == Delivery.ACTIVE,
                Ad.lead_form_external_id != "",
            )
            .order_by(Ad.name)
        )
    )
    if not ads:
        return []
    leads = countable_leads(db, owner=owner).where(
        Lead.ad_external_id.in_([ad.external_id for ad in ads])
    )
    if since is not None:
        leads = leads.where(Lead.submitted_at >= since)
    sub = leads.subquery()
    counts = dict(
        db.execute(
            select(sub.c.ad_external_id, func.count(sub.c.id)).group_by(
                sub.c.ad_external_id
            )
        ).all()
    )
    forms = dict(
        db.execute(
            select(LeadForm.external_id, LeadForm.name).where(
                LeadForm.owner_id == owner.id,
                LeadForm.external_id.in_({ad.lead_form_external_id for ad in ads}),
            )
        ).all()
    )
    return [
        AdOption(
            external_id=ad.external_id,
            title=ad.name or ad.external_id,
            form_name=forms.get(ad.lead_form_external_id, ""),
            leads=counts.get(ad.external_id, 0),
        )
        for ad in ads
    ]


@dataclass(frozen=True, slots=True)
class BoardFilters:
    query: str = ""
    member: str = ""
    ad: str = ""
    flag: str = ""

    def as_params(self) -> dict[str, str]:
        pairs = {"q": self.query, "m": self.member, "ad": self.ad, "f": self.flag}
        return {key: value for key, value in pairs.items() if value}


NO_FILTERS = BoardFilters()


def read_filters(
    *, q: str = "", m: str = "", ad: str = "", f: str = ""
) -> BoardFilters:
    return BoardFilters(
        query=q.strip()[:80],
        member=m[:40],
        ad=ad[:64],
        flag=f if f in {item.value for item in Flag} else "",
    )


@dataclass(frozen=True, slots=True)
class Column:
    stage: CrmStage
    cards: list[CrmCard]
    total: int
    won_minor: int = 0
    reasons: tuple[tuple[str, int], ...] = ()
    start: int = 0

    @property
    def hidden(self) -> int:
        return max(self.total - self.start - len(self.cards), 0)

    @property
    def next_start(self) -> int:
        return self.start + len(self.cards)

    @property
    def key(self) -> str:
        return str(self.stage.id)


@dataclass(frozen=True, slots=True)
class Board:
    columns: list[Column]
    late: int
    today: int
    cursor: str
    ads: dict[str, str] = field(default_factory=dict)

    @property
    def totals(self) -> dict[str, int]:
        return {column.key: column.total for column in self.columns}


def _visible(viewer: Viewer) -> ColumnElement[bool]:
    mine = CrmCard.owner_id == viewer.owner.id
    if viewer.is_owner:
        return mine
    new_stages = select(CrmStage.id).where(
        CrmStage.owner_id == viewer.owner.id, CrmStage.kind == StageKind.NEW
    )
    return and_(
        mine,
        or_(
            CrmCard.assignee_id == viewer.user.id,
            and_(CrmCard.assignee_id.is_(None), CrmCard.stage_id.in_(new_stages)),
        ),
    )


def visible_cards(viewer: Viewer) -> Select[tuple[CrmCard]]:
    return select(CrmCard).where(_visible(viewer))


def _today(now: datetime) -> tuple[datetime, datetime]:
    start = localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _narrowed(
    query: Select[Any], *, filters: BoardFilters, viewer: Viewer, now: datetime
) -> Select[Any]:
    if filters.query or filters.ad:
        query = query.join(Lead, Lead.id == CrmCard.lead_id)
    if filters.query:
        term = filters.query
        query = query.where(
            or_(
                Lead.full_name.icontains(term),
                Lead.phone_e164.icontains(term.replace(" ", "")),
            )
        )
    if filters.member and viewer.is_owner:
        if filters.member == "none":
            query = query.where(CrmCard.assignee_id.is_(None))
        else:
            try:
                query = query.where(CrmCard.assignee_id == uuid.UUID(filters.member))
            except ValueError:
                pass
    if filters.ad:
        query = query.where(Lead.ad_external_id == filters.ad)
    if filters.flag == Flag.LATE:
        query = query.where(CrmCard.due_at < now, CrmCard.closed_at.is_(None))
    elif filters.flag == Flag.TODAY:
        start, end = _today(now)
        query = query.where(
            CrmCard.due_at >= start, CrmCard.due_at < end, CrmCard.closed_at.is_(None)
        )
    return query


def _on_board(*, viewer: Viewer, filters: BoardFilters, now: datetime) -> Select[Any]:
    base = _narrowed(visible_cards(viewer), filters=filters, viewer=viewer, now=now)
    recent = now - timedelta(days=CLOSED_DAYS_ON_BOARD)
    return base.where(or_(CrmCard.closed_at.is_(None), CrmCard.closed_at >= recent))


def _ordered(query: Select[Any], kind: str) -> Select[Any]:
    if kind == StageKind.NEW:
        return query.order_by(CrmCard.created_at.desc(), CrmCard.id)
    if kind in (StageKind.WON, StageKind.LOST):
        return query.order_by(CrmCard.closed_at.desc(), CrmCard.id)
    return query.order_by(CrmCard.due_at, CrmCard.updated_at.desc(), CrmCard.id)


def _count(db: Session, query: Select[Any]) -> int:
    return int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)


def column_page(
    db: Session,
    *,
    viewer: Viewer,
    filters: BoardFilters,
    stage_id: str,
    start: int,
    now: datetime,
) -> Column | None:
    try:
        key = uuid.UUID(stage_id)
    except ValueError:
        return None
    stage = db.scalar(
        select(CrmStage).where(CrmStage.owner_id == viewer.owner.id, CrmStage.id == key)
    )
    if stage is None:
        return None
    in_stage = _on_board(viewer=viewer, filters=filters, now=now).where(
        CrmCard.stage_id == stage.id
    )
    cards = list(
        db.scalars(_ordered(in_stage, stage.kind).offset(start).limit(CARDS_PER_COLUMN))
    )
    return Column(stage=stage, cards=cards, total=_count(db, in_stage), start=start)


def _stamp(moment: datetime | None) -> str:
    return f"{moment.timestamp():.6f}" if moment else "0"


def cursor_of(db: Session, *, viewer: Viewer) -> str:
    cards_at, cards_n = db.execute(
        select(func.max(CrmCard.updated_at), func.count(CrmCard.id)).where(
            _visible(viewer)
        )
    ).one()
    stages_at, stages_n = db.execute(
        select(func.max(CrmStage.updated_at), func.count(CrmStage.id)).where(
            CrmStage.owner_id == viewer.owner.id
        )
    ).one()
    setup = db.scalar(
        select(CrmSetup.updated_at).where(CrmSetup.owner_id == viewer.owner.id)
    )
    return "|".join(
        (
            f"{cards_n}-{_stamp(cards_at)}",
            f"{stages_n}-{_stamp(stages_at)}-{_stamp(setup)}",
        )
    )


def layout_changed(*, before: str, now: str) -> bool:
    return before.partition("|")[2] != now.partition("|")[2]


def board(
    db: Session, *, viewer: Viewer, filters: BoardFilters = NO_FILTERS, now: datetime
) -> Board:
    from app.modules.ads.selectors import ad_labels

    stages = stages_of(db, owner=viewer.owner)
    base = _on_board(viewer=viewer, filters=filters, now=now)
    sub = base.subquery()
    totals = dict(
        db.execute(
            select(sub.c.stage_id, func.count(sub.c.id)).group_by(sub.c.stage_id)
        ).all()
    )
    columns = []
    for stage in stages:
        in_stage = base.where(CrmCard.stage_id == stage.id)
        cards = list(db.scalars(_ordered(in_stage, stage.kind).limit(CARDS_PER_COLUMN)))
        won = 0
        reasons: tuple[tuple[str, int], ...] = ()
        inner = in_stage.subquery()
        if stage.kind == StageKind.WON:
            won = int(db.scalar(select(func.sum(inner.c.won_amount_minor))) or 0)
        elif stage.kind == StageKind.LOST:
            reasons = tuple(
                (name or "—", n)
                for name, n in db.execute(
                    select(inner.c.lost_reason_name, func.count(inner.c.id))
                    .group_by(inner.c.lost_reason_name)
                    .order_by(func.count(inner.c.id).desc())
                    .limit(LOST_REASONS_SHOWN)
                )
            )
        columns.append(
            Column(
                stage=stage,
                cards=cards,
                total=totals.get(stage.id, 0),
                won_minor=won,
                reasons=reasons,
            )
        )
    leads = {card.lead_id for column in columns for card in column.cards}
    ad_ids = set(
        db.scalars(
            select(Lead.ad_external_id).where(
                Lead.id.in_(leads), Lead.ad_external_id != ""
            )
        )
    )
    open_cards = visible_cards(viewer).where(CrmCard.closed_at.is_(None))
    start, end = _today(now)
    late = _count(db, open_cards.where(CrmCard.due_at < now))
    today = _count(db, open_cards.where(CrmCard.due_at >= start, CrmCard.due_at < end))
    names = ad_labels(db, owner=viewer.owner, external_ids=ad_ids)
    return Board(
        columns=columns,
        late=late,
        today=today,
        cursor=cursor_of(db, viewer=viewer),
        ads={key: label.title for key, label in names.items()},
    )


def placed_card(db: Session, *, viewer: Viewer, card_id: str) -> CrmCard | None:
    try:
        key = uuid.UUID(card_id)
    except ValueError:
        return None
    return db.scalar(visible_cards(viewer).where(CrmCard.id == key))


def attention_count(db: Session, *, viewer: Viewer, now: datetime) -> int:
    new_stages = select(CrmStage.id).where(
        CrmStage.owner_id == viewer.owner.id, CrmStage.kind == StageKind.NEW
    )
    return _count(
        db,
        visible_cards(viewer).where(
            CrmCard.closed_at.is_(None),
            or_(
                CrmCard.due_at < now,
                and_(CrmCard.assignee_id.is_(None), CrmCard.stage_id.in_(new_stages)),
            ),
        ),
    )


def board_ads(db: Session, *, viewer: Viewer, now: datetime) -> list[tuple[str, str]]:
    from app.modules.ads.selectors import ad_labels

    recent = now - timedelta(days=CLOSED_DAYS_ON_BOARD)
    ids = set(
        db.scalars(
            select(Lead.ad_external_id)
            .join(CrmCard, CrmCard.lead_id == Lead.id)
            .where(
                _visible(viewer),
                or_(CrmCard.closed_at.is_(None), CrmCard.closed_at >= recent),
                Lead.ad_external_id != "",
            )
            .distinct()
        )
    )
    names = ad_labels(db, owner=viewer.owner, external_ids=ids)
    options = [(key, names[key].title if key in names else key) for key in ids]
    return sorted(options, key=lambda pair: pair[1].lower())


@dataclass(frozen=True, slots=True)
class CardView:
    card: CrmCard
    answers: tuple[Any, ...]
    source: Any
    history: list[CrmActivity]
    stages: list[CrmStage]
    members: list[CrmMember]
    reasons: list[CrmLostReason]
    currency: str

    @property
    def can_work(self) -> bool:
        return self.card.closed_at is None


def card_view(db: Session, *, viewer: Viewer, card_id: str) -> CardView | None:
    from app.modules.ads.selectors import ad_label
    from app.modules.leads.selectors import answer_rows

    card = placed_card(db, viewer=viewer, card_id=card_id)
    if card is None:
        return None
    history = list(
        db.scalars(
            select(CrmActivity)
            .where(
                CrmActivity.owner_id == viewer.owner.id, CrmActivity.card_id == card.id
            )
            .order_by(CrmActivity.created_at.desc())
            .limit(HISTORY_SHOWN)
        )
    )
    lead = card.lead
    source = (
        ad_label(db, owner=viewer.owner, external_id=lead.ad_external_id)
        if lead.ad_external_id
        else None
    )
    setup = setup_of(db, owner=viewer.owner)
    return CardView(
        card=card,
        answers=tuple(a for a in answer_rows(lead=lead) if a.key not in CONTACT_KEYS),
        source=source,
        history=history,
        stages=stages_of(db, owner=viewer.owner),
        members=active_members(db, owner=viewer.owner),
        reasons=reasons_of(db, owner=viewer.owner),
        currency=setup.currency if setup else "",
    )


@dataclass(frozen=True, slots=True)
class LeadPlace:
    stage_name: str
    color: str
    assignee: str


def lead_places(
    db: Session, *, owner: User, lead_ids: Iterable[uuid.UUID | str]
) -> dict[str, LeadPlace]:
    ids = [uuid.UUID(str(i)) for i in lead_ids]
    if not ids:
        return {}
    rows = db.execute(
        select(
            CrmCard.lead_id, CrmStage.name, CrmStage.color, User.full_name, User.email
        )
        .join(CrmStage, CrmStage.id == CrmCard.stage_id)
        .outerjoin(User, User.id == CrmCard.assignee_id)
        .where(CrmCard.owner_id == owner.id, CrmCard.lead_id.in_(ids))
    )
    return {
        str(lead): LeadPlace(stage_name=name, color=color, assignee=full or email or "")
        for lead, name, color, full, email in rows
    }


def qualified_count(
    db: Session,
    *,
    owner: User,
    since: datetime,
    until: datetime,
    campaign_ids: Collection[str] | None = None,
) -> int | None:
    if not is_running(db, owner=owner):
        return None
    marked = db.scalar(
        select(CrmStage.id).where(
            CrmStage.owner_id == owner.id, CrmStage.counts_as_quality.is_(True)
        )
    )
    if marked is None and not db.scalar(
        select(CrmCard.id).where(
            CrmCard.owner_id == owner.id, CrmCard.qualified_at.is_not(None)
        )
    ):
        return None
    query = select(CrmCard.id).where(
        CrmCard.owner_id == owner.id,
        CrmCard.qualified_at >= since,
        CrmCard.qualified_at < until,
    )
    if campaign_ids is not None:
        query = query.join(Lead, Lead.id == CrmCard.lead_id).where(
            Lead.campaign_external_id.in_(list(campaign_ids))
        )
    return _count(db, query)


def ad_names_for(db: Session, *, owner: User, cards: list[CrmCard]) -> dict[str, str]:
    from app.modules.ads.selectors import ad_labels

    ids = {card.lead.ad_external_id for card in cards if card.lead.ad_external_id}
    return {
        key: label.title
        for key, label in ad_labels(db, owner=owner, external_ids=ids).items()
    }
