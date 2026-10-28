import uuid
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, false, func, or_, select
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.common.db import utcnow
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
from app.modules.integrations.selectors import Pair, current_pair, page_pairs
from app.modules.leads.models import Lead, LeadForm

HISTORY_SHOWN = 40
CONTACT_KEYS = frozenset({"full_name", "phone_number", "email", "city"})


@dataclass(frozen=True, slots=True)
class Scope:
    """One page and ad account pair's CRM: every row of it carries these three."""

    owner_id: uuid.UUID
    page_id: uuid.UUID
    ad_account_id: uuid.UUID

    @classmethod
    def of(cls, pair: Pair) -> "Scope":
        return cls(
            owner_id=pair.page.owner_id,
            page_id=pair.page.id,
            ad_account_id=pair.account.id,
        )

    def holds(self, model: Any) -> ColumnElement[bool]:
        return and_(
            model.owner_id == self.owner_id,
            model.page_id == self.page_id,
            model.ad_account_id == self.ad_account_id,
        )

    def fields(self) -> dict[str, uuid.UUID]:
        return {
            "owner_id": self.owner_id,
            "page_id": self.page_id,
            "ad_account_id": self.ad_account_id,
        }


def holds(scope: "Scope | None", model: Any) -> ColumnElement[bool]:
    return scope.holds(model) if scope is not None else false()


@dataclass(frozen=True, slots=True)
class Viewer:
    """The reader of a CRM screen, on one pair's CRM.

    The owner picks the pair; a manager works in the one pair they were
    added to. ``pair`` is ``None`` when the owner has no pair yet, or the
    manager's pair has left the subscription.
    """

    owner: User
    user: User
    member: CrmMember | None
    pair: Pair | None = None
    pairs: tuple[Pair, ...] = ()
    # Whether a manager sits in a seat: the free one of their page, or a
    # bought one. Always true for the owner.
    seated: bool = True

    @property
    def is_owner(self) -> bool:
        return self.member is None and self.user.id == self.owner.id

    @property
    def scope(self) -> Scope | None:
        return Scope.of(self.pair) if self.pair is not None else None

    @property
    def may_work(self) -> bool:
        if self.is_owner:
            return True
        return (
            self.member is not None
            and self.member.is_active
            and self.seated
            and self.pair is not None
            and bool(self.owner.is_active)
        )


def chosen_pair(
    db: Session, *, owner: User, wanted: str, pairs: Sequence[Pair]
) -> Pair | None:
    """``wanted`` when it is one of ``pairs``, else the cabinet's current pair."""
    found = next((pair for pair in pairs if pair.key == wanted), None)
    if found is not None or not pairs:
        return found
    return current_pair(db, owner=owner, pairs=pairs)


def pair_of_row(pairs: Sequence[Pair], row: Any) -> Pair | None:
    return next(
        (
            pair
            for pair in pairs
            if pair.page.id == row.page_id and pair.account.id == row.ad_account_id
        ),
        None,
    )


def viewer_for(db: Session, *, user: User, wanted: str = "") -> Viewer:
    if user.crm_owner_id is None:
        pairs = tuple(page_pairs(db, owner=user))
        return Viewer(
            owner=user,
            user=user,
            member=None,
            pair=chosen_pair(db, owner=user, wanted=wanted, pairs=pairs),
            pairs=pairs,
        )
    member = db.scalar(select(CrmMember).where(CrmMember.user_id == user.id))
    owner_id = member.owner_id if member is not None else user.crm_owner_id
    owner = db.get(User, owner_id) or user
    if member is None:
        return Viewer(owner=owner, user=user, member=None)
    pairs = tuple(page_pairs(db, owner=owner))
    return Viewer(
        owner=owner,
        user=user,
        member=member,
        pair=pair_of_row(pairs, member),
        pairs=pairs,
        seated=member.id in seated_ids(db, owner=owner, at=utcnow()),
    )


def viewer_on_card(db: Session, *, viewer: Viewer, card_id: str) -> Viewer | None:
    """The owner moved onto the pair a card opened by its link belongs to.

    A manager stays on their own pair; ``None`` when the card is on no pair
    the reader may open.
    """
    try:
        key = uuid.UUID(card_id)
    except ValueError:
        return None
    card = db.scalar(
        select(CrmCard).where(CrmCard.owner_id == viewer.owner.id, CrmCard.id == key)
    )
    if card is None:
        return None
    pair = pair_of_row(viewer.pairs, card)
    if pair is None:
        return None
    if not viewer.is_owner:
        return viewer if pair == viewer.pair else None
    return replace(viewer, pair=pair)


def seated_ids(db: Session, *, owner: User, at: datetime) -> frozenset[uuid.UUID]:
    """The active managers inside a seat, oldest first.

    A paid plan seats one manager free on each page of the subscription,
    and that seat works only on its own page. The managers it does not
    seat share the seats bought, in the order they were added; the rest
    wait, locked out and handed no leads.
    """
    from app.modules.billing.selectors import live_subscription
    from app.modules.billing.selectors.seats import paid_seats

    seated, waiting = _free_seating(
        db, owner=owner, subscription=live_subscription(db, owner=owner)
    )
    if not waiting:
        return frozenset(seated)
    return frozenset(seated | set(waiting[: paid_seats(db, owner=owner, at=at)]))


def seat_capacity(db: Session, *, owner: User, at: datetime) -> int:
    """How many managers may work: a free seat per page of a paid plan, plus
    the seats bought and running at ``at``."""
    from app.modules.billing.constants import SubscriptionStatus
    from app.modules.billing.selectors import live_subscription
    from app.modules.billing.selectors.seats import paid_seats
    from app.modules.integrations.selectors import enabled_pages

    subscription = live_subscription(db, owner=owner)
    free = (
        0
        if subscription is None or subscription.status == SubscriptionStatus.TRIAL
        else len(enabled_pages(db, owner=owner))
    )
    return free + paid_seats(db, owner=owner, at=at)


def team_size(db: Session, *, owner: User) -> int:
    """Active managers across every pair of the owner's."""
    return int(
        db.scalar(
            select(func.count(CrmMember.id)).where(
                CrmMember.owner_id == owner.id, CrmMember.is_active.is_(True)
            )
        )
        or 0
    )


def unseated_count(db: Session, *, owner: User, subscription: Any) -> int:
    """Active managers the plan's free page seats leave waiting for a bought one."""
    return len(_free_seating(db, owner=owner, subscription=subscription)[1])


def _free_seating(
    db: Session, *, owner: User, subscription: Any
) -> tuple[set[uuid.UUID], list[uuid.UUID]]:
    """Who a free page seat holds, and who waits beyond them, oldest first."""
    from app.modules.billing.constants import SubscriptionStatus
    from app.modules.integrations.selectors import enabled_pages

    members = list(
        db.scalars(
            select(CrmMember)
            .where(CrmMember.owner_id == owner.id, CrmMember.is_active.is_(True))
            .order_by(CrmMember.created_at, CrmMember.id)
        )
    )
    if not members:
        return set(), []
    free_pages: set[uuid.UUID] = (
        set()
        if subscription is None or subscription.status == SubscriptionStatus.TRIAL
        else {page.id for page in enabled_pages(db, owner=owner)}
    )
    seated: set[uuid.UUID] = set()
    used: set[uuid.UUID] = set()
    waiting: list[uuid.UUID] = []
    for member in members:
        if member.page_id in free_pages and member.page_id not in used:
            used.add(member.page_id)
            seated.add(member.id)
        else:
            waiting.append(member.id)
    return seated, waiting


def crm_open(db: Session | None = None, *, owner: User) -> bool:
    return True


def setup_of(db: Session, *, scope: Scope | None) -> CrmSetup | None:
    if scope is None:
        return None
    return db.scalar(select(CrmSetup).where(scope.holds(CrmSetup)))


def is_running(db: Session, *, owner: User) -> bool:
    """Whether any of the owner's pairs runs a CRM."""
    return (
        db.scalar(
            select(CrmSetup.id)
            .where(
                CrmSetup.owner_id == owner.id,
                CrmSetup.page_id.is_not(None),
                CrmSetup.state == SetupState.ON,
            )
            .limit(1)
        )
        is not None
    )


def stages_of(db: Session, *, scope: Scope | None) -> list[CrmStage]:
    return list(
        db.scalars(
            select(CrmStage)
            .where(holds(scope, CrmStage))
            .order_by(CrmStage.position, CrmStage.created_at)
        )
    )


def stage_of_kind(db: Session, *, scope: Scope, kind: str) -> CrmStage | None:
    return db.scalar(
        select(CrmStage)
        .where(scope.holds(CrmStage), CrmStage.kind == kind)
        .order_by(CrmStage.position)
        .limit(1)
    )


def members_of(db: Session, *, scope: Scope | None) -> list[CrmMember]:
    return list(
        db.scalars(
            select(CrmMember)
            .where(holds(scope, CrmMember))
            .order_by(CrmMember.created_at)
        )
    )


def active_members(db: Session, *, scope: Scope | None) -> list[CrmMember]:
    return [member for member in members_of(db, scope=scope) if member.is_active]


def reasons_of(db: Session, *, scope: Scope | None) -> list[CrmLostReason]:
    return list(
        db.scalars(
            select(CrmLostReason)
            .where(holds(scope, CrmLostReason))
            .order_by(CrmLostReason.position, CrmLostReason.created_at)
        )
    )


def pair_conditions(
    db: Session, *, owner: User, pairs: Sequence[Pair]
) -> dict[str, ColumnElement[bool]]:
    """``{pair key: its leads, as a condition on Lead}``.

    A pair's leads come from the campaigns this product launched from that
    page and account. A campaign launched before launches named their page
    says only its account, so its lead joins the pair whose page the lead
    itself names.
    """
    from app.modules.ads.selectors.owned import campaigns_by_pair
    from app.modules.integrations.selectors import enabled_pages
    from app.modules.leads.selectors import lead_scope

    campaigns = campaigns_by_pair(db, owner=owner, pairs=pairs)
    if not campaigns:
        return {}
    sole = len(enabled_pages(db, owner=owner)) == 1
    found: dict[str, ColumnElement[bool]] = {}
    for pair in pairs:
        own = campaigns[pair.key]
        condition: ColumnElement[bool] = Lead.campaign_external_id.in_(
            sorted(own.exact)
        )
        if own.pageless:
            condition = or_(
                condition,
                and_(
                    Lead.campaign_external_id.in_(sorted(own.pageless)),
                    lead_scope(page=pair.page, sole=sole),
                ),
            )
        found[pair.key] = condition
    return found


def countable_leads(
    db: Session, *, owner: User, pair: Pair | None = None
) -> Select[tuple[Lead]]:
    """The leads the CRM takes, of one pair or - with ``None`` - of any.

    From an advert this product launched from one of the subscription's
    pairs, on a paid page. A campaign built in Ads Manager, a test lead
    Meta sends with no advert behind it, and an advert paid from an account
    the page is not paired with are all left off.
    """
    from app.modules.leads.selectors import subscribed_lead_scope

    pairs = page_pairs(db, owner=owner)
    if pair is not None:
        pairs = [each for each in pairs if each.key == pair.key]
    conditions = list(pair_conditions(db, owner=owner, pairs=pairs).values())
    return select(Lead).where(
        Lead.owner_id == owner.id,
        Lead.is_test.is_(False),
        Lead.is_organic.is_(False),
        or_(*conditions) if conditions else false(),
        subscribed_lead_scope(db, owner=owner),
    )


def pair_of_lead(db: Session, *, owner: User, lead_id: uuid.UUID) -> Pair | None:
    """The pair whose CRM ``lead`` belongs on, or ``None``."""
    from app.modules.leads.selectors import subscribed_lead_scope

    pairs = page_pairs(db, owner=owner)
    conditions = pair_conditions(db, owner=owner, pairs=pairs)
    base = select(Lead.id).where(
        Lead.id == lead_id,
        Lead.owner_id == owner.id,
        Lead.is_test.is_(False),
        Lead.is_organic.is_(False),
        subscribed_lead_scope(db, owner=owner),
    )
    for pair in pairs:
        condition = conditions.get(pair.key)
        if condition is not None and db.scalar(base.where(condition)) is not None:
            return pair
    return None


@dataclass(frozen=True, slots=True)
class AdOption:
    external_id: str
    title: str
    form_name: str
    leads: int


def lead_ads(
    db: Session, *, owner: User, pair: Pair | None, since: datetime | None
) -> list[AdOption]:
    """The running lead adverts of ``pair``'s campaigns, for picking which land."""
    from app.modules.ads.constants import Delivery
    from app.modules.ads.models import Ad, AdSet, Campaign
    from app.modules.ads.selectors.owned import campaigns_by_pair

    if pair is None:
        return []
    own = campaigns_by_pair(db, owner=owner, pairs=[pair]).get(pair.key)
    campaign_ids = sorted(own.exact | own.pageless) if own else []
    if not campaign_ids:
        return []
    ads = list(
        db.scalars(
            select(Ad)
            .join(AdSet, AdSet.id == Ad.adset_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(
                Ad.owner_id == owner.id,
                Ad.delivery == Delivery.ACTIVE,
                Ad.lead_form_external_id != "",
                Campaign.external_id.in_(campaign_ids),
            )
            .order_by(Ad.name)
        )
    )
    if not ads:
        return []
    leads = countable_leads(db, owner=owner, pair=pair).where(
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
    mine = holds(viewer.scope, CrmCard)
    if viewer.is_owner:
        return mine
    new_stages = select(CrmStage.id).where(
        holds(viewer.scope, CrmStage), CrmStage.kind == StageKind.NEW
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
        select(CrmStage).where(holds(viewer.scope, CrmStage), CrmStage.id == key)
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
            holds(viewer.scope, CrmStage)
        )
    ).one()
    setup = db.scalar(select(CrmSetup.updated_at).where(holds(viewer.scope, CrmSetup)))
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

    stages = stages_of(db, scope=viewer.scope)
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
        holds(viewer.scope, CrmStage), CrmStage.kind == StageKind.NEW
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
    setup = setup_of(db, scope=viewer.scope)
    return CardView(
        card=card,
        answers=tuple(a for a in answer_rows(lead=lead) if a.key not in CONTACT_KEYS),
        source=source,
        history=history,
        stages=stages_of(db, scope=viewer.scope),
        members=active_members(db, scope=viewer.scope),
        reasons=reasons_of(db, scope=viewer.scope),
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
