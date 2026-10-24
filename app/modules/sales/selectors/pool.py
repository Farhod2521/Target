"""The pool: accounts worth a call, grouped and ordered by why."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Select,
    Subquery,
    and_,
    case,
    exists,
    func,
    literal,
    or_,
    select,
    true,
)
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.public.models import ConsultRequest
from app.modules.sales.constants import (
    BACK_WINDOW_DAYS,
    GROUP_LABELS,
    GROUP_ORDER,
    NEW_WINDOW_DAYS,
    PROBLEM_AFTER_HOURS,
    Group,
    Outcome,
)
from app.modules.sales.models import ContactHold, LostReason, SalesClaim, SalesSegment
from app.modules.sales.selectors.arizas import (
    ariza_queue,
    count_of,
    load_arizas,
    queued_ariza,
)
from app.modules.sales.selectors.search import account_match

ALL = "all"
SEGMENT_PREFIX = "seg-"
NEVER = datetime(2000, 1, 1, tzinfo=UTC)
ACCOUNT_FIELDS = (
    "live_expires",
    "live_plan_id",
    "live_plan_name",
    "live_status",
    "live_started",
    "last_plan_name",
    "last_ended",
    "has_paid",
    "is_referred",
    "is_claimed",
    "is_held",
    "last_outcome",
    "last_closed",
    "last_reason",
    "talked_at",
    "asked_at",
    "launched_meta",
    "launched_google",
)
GROUP_FIELDS = ("group", "rank", "is_problem", "is_asked")
_ARIZA_RANK = GROUP_ORDER.index(Group.ARIZA)


@dataclass(frozen=True, slots=True)
class Chip:
    key: str
    label: str
    count: int


def _live(column: Any, *, now: datetime) -> Any:
    from app.modules.billing.constants import LIVE_SUBSCRIPTION_STATUSES
    from app.modules.billing.models import Plan, Subscription

    return (
        select(column)
        .select_from(Subscription)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(
            Subscription.owner_id == User.id,
            Subscription.status.in_([str(s) for s in LIVE_SUBSCRIPTION_STATUSES]),
            Subscription.expires_at > now,
        )
        .order_by(Subscription.started_at.desc())
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )


def _last_ended(column: Any) -> Any:
    from app.modules.billing.models import Plan, Subscription

    ended = func.coalesce(Subscription.ended_at, Subscription.expires_at)
    return (
        select(ended if column is None else column)
        .select_from(Subscription)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(Subscription.owner_id == User.id)
        .order_by(ended.desc())
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )


def _last_claim(column: Any, *, talks_only: bool = False) -> Any:
    query = (
        select(column)
        .select_from(SalesClaim)
        .outerjoin(LostReason, LostReason.id == SalesClaim.reason_id)
        .where(SalesClaim.owner_id == User.id, SalesClaim.closed_at.is_not(None))
    )
    if talks_only:
        query = query.where(SalesClaim.outcome != str(Outcome.RETURNED))
    return (
        query.order_by(SalesClaim.closed_at.desc())
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )


def _created_since(model: Any, *, started: Any) -> Any:
    from app.modules.ads.constants import LaunchStatus

    return exists(
        select(model.id).where(
            model.owner_id == User.id,
            model.status == str(LaunchStatus.CREATED),
            model.finished_at >= started,
        )
    )


def accounts(*, now: datetime) -> Subquery:
    """Every customer account with what the board decides on, one row each."""
    from app.modules.ads.models import CampaignLaunch, GoogleLaunch
    from app.modules.billing.constants import InvoiceStatus
    from app.modules.billing.models import Invoice, Plan, Subscription
    from app.modules.referrals.models import ReferralBinding

    live_started = _live(Subscription.started_at, now=now)
    talked_at = func.coalesce(
        _last_claim(SalesClaim.closed_at, talks_only=True), literal(NEVER)
    )
    asked_at = (
        select(ConsultRequest.updated_at)
        .where(
            ConsultRequest.phone_e164 == User.phone,
            ConsultRequest.contacted_at.is_(None),
            ConsultRequest.updated_at > talked_at,
        )
        .order_by(ConsultRequest.updated_at.desc())
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )
    return (
        select(
            User.id.label("id"),
            User.full_name.label("full_name"),
            User.email.label("email"),
            User.phone.label("phone"),
            User.date_joined.label("date_joined"),
            _live(Subscription.expires_at, now=now).label("live_expires"),
            _live(Subscription.plan_id, now=now).label("live_plan_id"),
            _live(Plan.name, now=now).label("live_plan_name"),
            _live(Subscription.status, now=now).label("live_status"),
            live_started.label("live_started"),
            _last_ended(Plan.name).label("last_plan_name"),
            _last_ended(None).label("last_ended"),
            exists(
                select(Invoice.id).where(
                    Invoice.owner_id == User.id,
                    Invoice.status == str(InvoiceStatus.PAID),
                )
            ).label("has_paid"),
            exists(
                select(ReferralBinding.id).where(ReferralBinding.owner_id == User.id)
            ).label("is_referred"),
            exists(
                select(SalesClaim.id).where(
                    SalesClaim.owner_id == User.id, SalesClaim.closed_at.is_(None)
                )
            ).label("is_claimed"),
            exists(
                select(ContactHold.id).where(
                    ContactHold.owner_id == User.id,
                    ContactHold.lifted_at.is_(None),
                    or_(ContactHold.until.is_(None), ContactHold.until > now),
                )
            ).label("is_held"),
            _last_claim(SalesClaim.outcome).label("last_outcome"),
            _last_claim(SalesClaim.closed_at).label("last_closed"),
            _last_claim(LostReason.label).label("last_reason"),
            talked_at.label("talked_at"),
            asked_at.label("asked_at"),
            _created_since(CampaignLaunch, started=live_started).label("launched_meta"),
            _created_since(GoogleLaunch, started=live_started).label("launched_google"),
        )
        .where(User.is_staff.is_(False), User.is_active.is_(True))
        .subquery("acc")
    )


class Conditions:
    """The pool's groups, written against one ``accounts`` subquery."""

    def __init__(self, acc: Subquery, *, now: datetime) -> None:
        self.c = acc.c
        self.now = now

    def asked(self) -> ColumnElement[bool]:
        return self.c.asked_at.is_not(None)

    def only(self, q: ColumnElement[bool]) -> ColumnElement[bool]:
        return and_(q, ~self.asked())

    def ending(self, *, days: int) -> ColumnElement[bool]:
        return and_(
            self.c.live_expires.is_not(None),
            self.c.live_expires <= self.now + timedelta(days=days),
        )

    def back(self) -> ColumnElement[bool]:
        return and_(
            self.c.live_expires.is_(None),
            self.c.has_paid.is_(True),
            self.c.last_ended >= self.now - timedelta(days=BACK_WINDOW_DAYS),
        )

    def new(self) -> ColumnElement[bool]:
        return and_(
            self.c.live_expires.is_(None),
            self.c.has_paid.is_(False),
            self.c.date_joined >= self.now - timedelta(days=NEW_WINDOW_DAYS),
        )

    def problem(self) -> ColumnElement[bool]:
        return and_(
            self.c.live_started <= self.now - timedelta(hours=PROBLEM_AFTER_HOURS),
            self.c.launched_meta.is_(False),
            self.c.launched_google.is_(False),
        )

    def segment(self, segment: SalesSegment) -> ColumnElement[bool]:
        return and_(
            self.ending(days=segment.days), self.c.live_plan_id == segment.plan_id
        )

    def ending_any(
        self, *, ending_days: int, extra: list[SalesSegment]
    ) -> ColumnElement[bool]:
        return or_(
            self.ending(days=ending_days), *[self.segment(item) for item in extra]
        )

    def any_group(
        self, *, ending_days: int, extra: list[SalesSegment]
    ) -> ColumnElement[bool]:
        return or_(
            self.ending_any(ending_days=ending_days, extra=extra),
            self.problem(),
            self.back(),
            self.new(),
            self.asked(),
        )

    def unheld(self, *, term: str) -> ColumnElement[bool]:
        base = and_(self.c.is_claimed.is_(False), self.c.is_held.is_(False))
        if not term:
            return base
        return and_(
            base,
            account_match(
                term,
                id_col=self.c.id,
                full_name=self.c.full_name,
                email=self.c.email,
                phone=self.c.phone,
            ),
        )

    def condition(
        self, *, key: str, ending_days: int, extra: list[SalesSegment]
    ) -> ColumnElement[bool]:
        if key == Group.ENDING:
            return self.ending(days=ending_days)
        if key == Group.PROBLEM:
            return self.problem()
        if key == Group.BACK:
            return self.only(self.back())
        if key == Group.NEW:
            return self.only(self.new())
        if key == Group.ARIZA:
            return self.asked()
        for segment in extra:
            if key == segment_key(segment):
                return self.segment(segment)
        return self.any_group(ending_days=ending_days, extra=extra)


@dataclass(frozen=True, slots=True)
class Queue:
    query: Select[Any]
    rank: Any


def _grouped(
    acc: Subquery,
    conditions: Conditions,
    *,
    ending_days: int,
    extra: list[SalesSegment],
) -> tuple[Any, Any, list[Any]]:
    meets = {
        Group.ENDING: conditions.ending_any(ending_days=ending_days, extra=extra),
        Group.PROBLEM: conditions.problem(),
        Group.ARIZA: conditions.asked(),
        Group.BACK: acc.c.has_paid.is_(True),
        Group.NEW: true(),
    }
    first = [(group, meets[group]) for group in GROUP_ORDER]
    group = case(
        *[(q, literal(str(name))) for name, q in first[:-1]],
        else_=literal(str(Group.NEW)),
    )
    rank = case(
        *[(q, literal(index)) for index, (_, q) in enumerate(first[:-1])],
        else_=literal(len(first) - 1),
    )
    soonest = case((rank < _ARIZA_RANK, acc.c.live_expires))
    columns = [
        group.label("group"),
        rank.label("rank"),
        meets[Group.PROBLEM].label("is_problem"),
        meets[Group.ARIZA].label("is_asked"),
    ]
    order = [
        rank,
        soonest,
        acc.c.asked_at.desc(),
        acc.c.last_ended.desc(),
        acc.c.date_joined.desc(),
    ]
    return rank, columns, order


def queue(
    *,
    now: datetime,
    ending_days: int,
    key: str = ALL,
    extra: list[SalesSegment],
    term: str = "",
) -> Queue:
    acc = accounts(now=now)
    conditions = Conditions(acc, now=now)
    rank, columns, order = _grouped(
        acc, conditions, ending_days=ending_days, extra=extra
    )
    query = (
        select(User, *[acc.c[name] for name in ACCOUNT_FIELDS], *columns)
        .join(acc, acc.c.id == User.id)
        .where(
            conditions.unheld(term=term),
            conditions.condition(key=key, ending_days=ending_days, extra=extra),
        )
        .order_by(*order)
    )
    return Queue(query=query, rank=rank)


def load_accounts(db: Session, query: Select[Any]) -> list[User]:
    rows = []
    for row in db.execute(query):
        user = row[0]
        user.is_request = False
        for name in (*ACCOUNT_FIELDS, *GROUP_FIELDS):
            if name in row._mapping:
                setattr(user, name, row._mapping[name])
        rows.append(user)
    return rows


def annotated_account(
    db: Session, *, client_id: uuid.UUID, now: datetime
) -> User | None:
    acc = accounts(now=now)
    found = load_accounts(
        db,
        select(User, *[acc.c[name] for name in ACCOUNT_FIELDS])
        .join(acc, acc.c.id == User.id)
        .where(User.id == client_id),
    )
    return found[0] if found else None


def segment_key(segment: SalesSegment) -> str:
    return f"{SEGMENT_PREFIX}{segment.id}"


def chips(
    db: Session,
    *,
    now: datetime,
    ending_days: int,
    extra: list[SalesSegment],
    term: str = "",
) -> list[Chip]:
    acc = accounts(now=now)
    conditions = Conditions(acc, now=now)
    keyed: list[tuple[str, str, ColumnElement[bool]]] = [
        (ALL, "", conditions.any_group(ending_days=ending_days, extra=extra)),
        (Group.ARIZA, GROUP_LABELS[Group.ARIZA], conditions.asked()),
        (Group.NEW, GROUP_LABELS[Group.NEW], conditions.only(conditions.new())),
        (Group.BACK, GROUP_LABELS[Group.BACK], conditions.only(conditions.back())),
        (Group.ENDING, GROUP_LABELS[Group.ENDING], conditions.ending(days=ending_days)),
        (Group.PROBLEM, GROUP_LABELS[Group.PROBLEM], conditions.problem()),
    ]
    for segment in extra:
        keyed.append(
            (
                segment_key(segment),
                "«%(plan)s» · %(days)s kun"
                % {"plan": segment.plan.name, "days": segment.days},
                conditions.segment(segment),
            )
        )
    counts = db.execute(
        select(
            *[
                func.count().filter(q).label(f"c{index}")
                for index, (_, _, q) in enumerate(keyed)
            ]
        )
        .select_from(acc)
        .where(conditions.unheld(term=term))
    ).one()
    found = [
        Chip(key=str(key), label=label, count=counts[index] or 0)
        for index, (key, label, _) in enumerate(keyed)
    ]
    arizas = count_of(db, ariza_queue(now=now, term=term))
    for index in (0, 1):
        found[index] = Chip(
            key=found[index].key,
            label=found[index].label,
            count=found[index].count + arizas,
        )
    return found


def pool_rows(
    db: Session,
    *,
    now: datetime,
    ending_days: int,
    key: str,
    extra: list[SalesSegment],
    offset: int,
    limit: int,
    term: str = "",
) -> list[User | ConsultRequest]:
    found = queue(now=now, ending_days=ending_days, key=key, extra=extra, term=term)
    if key not in (ALL, Group.ARIZA):
        return list(load_accounts(db, found.query.offset(offset).limit(limit)))
    sources: list[tuple[Select[Any], bool]] = [
        (found.query.where(found.rank < _ARIZA_RANK), False),
        (ariza_queue(now=now, term=term), True),
        (found.query.where(found.rank >= _ARIZA_RANK), False),
    ]
    rows: list[User | ConsultRequest] = []
    for source, is_ariza in sources:
        if limit == 0:
            break
        page = source.offset(offset).limit(limit)
        taken: list[Any] = (
            load_arizas(db, page) if is_ariza else load_accounts(db, page)
        )
        rows += taken
        limit -= len(taken)
        offset = 0 if taken else max(offset - count_of(db, source), 0)
    return rows


def group_now(
    db: Session,
    *,
    client_id: uuid.UUID,
    now: datetime,
    ending_days: int,
    extra: list[SalesSegment],
) -> str | None:
    found = queue(now=now, ending_days=ending_days, extra=extra)
    row = db.execute(found.query.where(User.id == client_id).limit(1)).first()
    if row is None and queued_ariza(db, consult_id=client_id, now=now) is not None:
        return str(Group.ARIZA)
    return row._mapping["group"] if row is not None else None


def queued_client(
    db: Session,
    *,
    client_id: uuid.UUID,
    now: datetime,
    ending_days: int,
    key: str,
    extra: list[SalesSegment],
    term: str = "",
) -> User | ConsultRequest | None:
    if key in (ALL, Group.ARIZA):
        consult = queued_ariza(db, consult_id=client_id, now=now, term=term)
        if consult is not None:
            return consult
    found = queue(now=now, ending_days=ending_days, key=key, extra=extra, term=term)
    rows = load_accounts(db, found.query.where(User.id == client_id).limit(1))
    return rows[0] if rows else None
