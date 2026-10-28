"""The customer list, and the search that finds one.

The one read in the office deliberately not scoped to an owner: it asks
"which account is it". A fixed number of queries whatever the page size -
the accounts, then one batched read per fact for the whole screenful.
"""

import re
import uuid
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from metaads.writing import is_dry_run_id
from sqlalchemy import ColumnElement, Select, false, func, or_, select, true
from sqlalchemy.orm import Session, joinedload

from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import NOT_RUNNING, LaunchStep
from app.modules.ads.models import Campaign, CampaignLaunch
from app.modules.backoffice.constants import EXPIRING_DAYS, PAGE_SIZE
from app.modules.backoffice.selectors.days import days_left
from app.modules.backoffice.selectors.problems import Problem, worst_by_owner
from app.modules.billing.constants import (
    LIVE_SUBSCRIPTION_STATUSES,
    InvoiceStatus,
    SubscriptionStatus,
)
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.billing.selectors import entitled_owner_ids
from app.modules.businesses.models import Business
from app.modules.integrations.models import AdAccount, PageAccount, PageInstagram
from app.modules.leads.models import Lead
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.sales.models import SalesClaim

STATES = (
    ("", "Hammasi"),
    ("trouble", "E'tibor kerak"),
    ("trial", "Sinovda"),
    ("active", "Faol"),
    ("expiring", "Tugayapti"),
    ("lapsed", "Obunasi tugagan"),
    ("never", "Obuna olmagan"),
)
SORTS = (
    ("", "Holatga qarab"),
    ("joined", "Yangi ro'yxatdan o'tganlar"),
    ("expires", "Muddati tugashi"),
    ("last_login", "Oxirgi kirish"),
)
NO_MANAGER = "none"
Money = tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class Narrowing:
    """What the operator asked the list for, every part optional.

    ``plan`` matches the tier the row shows: the live one, else the last
    that ended. ``manager`` is a sales manager's id, or ``none`` for
    accounts no manager holds. The days are the office's calendar days.
    """

    term: str = ""
    state: str = ""
    plan: str = ""
    joined_from: date | None = None
    joined_to: date | None = None
    manager: str = ""
    sort: str = ""


@dataclass(frozen=True, slots=True)
class PageCount:
    used: int
    allowed: int | None


@dataclass(frozen=True, slots=True)
class CustomerRow:
    user: User
    business: Business | None
    subscription: Subscription | None
    days_left: int | None
    ended: Subscription | None
    ended_on: datetime | None
    trouble: Problem | None
    pages: PageCount | None
    running: int
    spend: Money
    leads: int
    paid_total: Money
    paid_before: bool
    manager: User | None


@dataclass(frozen=True, slots=True)
class CustomerPage:
    rows: tuple[CustomerRow, ...]
    total: int
    offset: int
    has_more: bool
    as_of: datetime

    @property
    def next_offset(self) -> int:
        return self.offset + len(self.rows)


# -- which accounts ------------------------------------------------------------------


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _by_term(db: Session, term: str) -> ColumnElement[bool]:
    """An address, a name, a telephone number, an invoice number, or an id
    copied out of Ads Manager - whatever the caller read out."""
    if not term:
        return true()
    like = f"%{term}%"
    digits = re.sub(r"[\s()-]", "", term) or term
    matches: list[ColumnElement[bool]] = [
        User.email.ilike(like),
        User.full_name.ilike(like),
        User.phone.ilike(f"%{digits}%"),
    ]
    owner_ids: set[uuid.UUID] = set()
    for column, owner in (
        (Invoice.number, Invoice.owner_id),
        (AdAccount.external_id, AdAccount.owner_id),
        (PageAccount.external_id, PageAccount.owner_id),
    ):
        owner_ids.update(
            found for found in db.scalars(select(owner).where(column == term)) if found
        )
    if owner_ids:
        matches.append(User.id.in_(owner_ids))
    return or_(*matches)


def _live(*, now: datetime) -> Select[Any]:
    return select(Subscription).where(
        Subscription.owner_id == User.id,
        Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
        Subscription.expires_at > now,
    )


def _stopped() -> ColumnElement[Any]:
    return func.coalesce(Subscription.ended_at, Subscription.expires_at)


def _by_state(
    state: str, *, now: datetime, troubled: set[uuid.UUID]
) -> ColumnElement[bool]:
    """Lapsed and never are two chips: folded together they bury the few who
    paid and stopped, the only ones a call can win back."""
    if state == "trouble":
        return User.id.in_(troubled) if troubled else false()
    if state in ("trial", "active"):
        wanted = (
            SubscriptionStatus.TRIAL if state == "trial" else SubscriptionStatus.ACTIVE
        )
        return User.id.in_(
            select(Subscription.owner_id).where(
                Subscription.status == wanted, Subscription.expires_at > now
            )
        )
    if state == "expiring":
        return User.id.in_(
            select(Subscription.owner_id).where(
                Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
                Subscription.expires_at >= now,
                Subscription.expires_at < now + timedelta(days=EXPIRING_DAYS),
            )
        )
    if state == "lapsed":
        return User.id.in_(select(Subscription.owner_id)) & User.id.not_in(
            entitled_owner_ids(now=now)
        )
    if state == "never":
        return User.id.not_in(select(Subscription.owner_id))
    return true()


def _by_plan(code: str, *, now: datetime) -> ColumnElement[bool]:
    if not code:
        return true()
    live = (
        _live(now=now)
        .join(Plan, Plan.id == Subscription.plan_id)
        .with_only_columns(Plan.code)
        .limit(1)
        .scalar_subquery()
    )
    last = (
        select(Plan.code)
        .join(Subscription, Subscription.plan_id == Plan.id)
        .where(Subscription.owner_id == User.id)
        .order_by(_stopped().desc())
        .limit(1)
        .scalar_subquery()
    )
    return func.coalesce(live, last) == code


def _by_joined(
    *, joined_from: date | None, joined_to: date | None, now: datetime
) -> ColumnElement[bool]:
    found: ColumnElement[bool] = true()
    if joined_from is not None:
        found &= User.date_joined >= datetime.combine(joined_from, time.min, now.tzinfo)
    if joined_to is not None:
        after = joined_to + timedelta(days=1)
        found &= User.date_joined < datetime.combine(after, time.min, now.tzinfo)
    return found


def _open_claims() -> Select[Any]:
    return select(SalesClaim.owner_id).where(
        SalesClaim.closed_at.is_(None),
        SalesClaim.manager_id.is_not(None),
        SalesClaim.owner_id.is_not(None),
    )


def _by_manager(manager: str) -> ColumnElement[bool]:
    if not manager:
        return true()
    if manager == NO_MANAGER:
        return User.id.not_in(_open_claims())
    wanted = _uuid(manager)
    if wanted is None:
        return false()
    return User.id.in_(_open_claims().where(SalesClaim.manager_id == wanted))


def _ordered(query: Select[Any], *, narrowing: Narrowing, now: datetime) -> Select[Any]:
    """Each chip in the order somebody works through it, unless a sort is named.

    Live ones soonest to end first; lapsed ones most recently lapsed first;
    everything else newest account first.
    """
    ends = (
        _live(now=now)
        .with_only_columns(Subscription.expires_at)
        .limit(1)
        .scalar_subquery()
    )
    sort = narrowing.sort
    if sort == "last_login":
        return query.order_by(
            User.last_login.desc().nulls_last(), User.date_joined.desc()
        )
    if sort == "joined":
        return query.order_by(User.date_joined.desc())
    if sort == "expires" or (
        not sort and narrowing.state in ("trial", "active", "expiring")
    ):
        return query.order_by(ends.asc().nulls_last(), User.date_joined.desc())
    if not sort and narrowing.state == "lapsed":
        stopped = (
            select(_stopped())
            .where(Subscription.owner_id == User.id)
            .order_by(_stopped().desc())
            .limit(1)
            .scalar_subquery()
        )
        return query.order_by(stopped.desc().nulls_last(), User.date_joined.desc())
    return query.order_by(User.date_joined.desc())


def narrowed_accounts(
    db: Session,
    narrowing: Narrowing,
    *,
    now: datetime,
    as_of: datetime,
    troubled: set[uuid.UUID],
) -> Select[Any]:
    """Customers only: staff and the CRM managers' own logins are not on it."""
    query = select(User).where(
        User.is_staff.is_(False),
        User.crm_owner_id.is_(None),
        User.date_joined <= as_of,
        _by_term(db, narrowing.term),
        _by_state(narrowing.state, now=now, troubled=troubled),
        _by_plan(narrowing.plan, now=now),
        _by_joined(
            joined_from=narrowing.joined_from, joined_to=narrowing.joined_to, now=now
        ),
        _by_manager(narrowing.manager),
    )
    return _ordered(query, narrowing=narrowing, now=now)


# -- what each row says --------------------------------------------------------------


def _profiles(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, Business]:
    """The first profile each account made; the rest are on its card."""
    found: dict[uuid.UUID, Business] = {}
    rows = db.scalars(
        select(Business)
        .options(joinedload(Business.direction))
        .where(Business.user_id.in_(ids))
        .order_by(Business.created_at)
    )
    for row in rows:
        found.setdefault(row.user_id, row)
    return found


def _subscriptions(
    db: Session, ids: list[uuid.UUID], *, now: datetime
) -> tuple[dict[uuid.UUID, Subscription], dict[uuid.UUID, Subscription]]:
    """Each account's live entitlement, and for the rest the last that ended."""
    live: dict[uuid.UUID, Subscription] = {}
    ended: dict[uuid.UUID, Subscription] = {}
    rows = db.scalars(
        select(Subscription)
        .options(joinedload(Subscription.plan))
        .where(Subscription.owner_id.in_(ids))
        .order_by(_stopped().desc())
    )
    for row in rows:
        if row.status in LIVE_SUBSCRIPTION_STATUSES and row.expires_at > now:
            live[row.owner_id] = row
        else:
            ended.setdefault(row.owner_id, row)
    return live, {owner: row for owner, row in ended.items() if owner not in live}


@dataclass(frozen=True, slots=True)
class _Activity:
    running: int = 0
    spend: Money = ()
    leads: int = 0


def _activity(
    db: Session, ids: list[uuid.UUID], *, now: datetime
) -> dict[uuid.UUID, _Activity]:
    """Adverts running, this month's spend and applications - only what this
    product launched, as every figure the office prints."""
    launched: dict[uuid.UUID, set[str]] = {}
    for owner_id, created_refs in db.execute(
        select(CampaignLaunch.owner_id, CampaignLaunch.created_refs).where(
            CampaignLaunch.owner_id.in_(ids)
        )
    ):
        for campaign in ref_field.ref_ids(created_refs or {}, LaunchStep.CAMPAIGN):
            if campaign and not is_dry_run_id(campaign):
                launched.setdefault(owner_id, set()).add(campaign)
    every = {campaign for campaigns in launched.values() for campaign in campaigns}
    if not every:
        return {}
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    running = dict(
        db.execute(
            select(Campaign.owner_id, func.count(Campaign.id))
            .where(
                Campaign.owner_id.in_(ids),
                Campaign.external_id.in_(every),
                Campaign.delivery.not_in(NOT_RUNNING),
            )
            .group_by(Campaign.owner_id)
        ).all()
    )
    spend: dict[uuid.UUID, list[tuple[str, int]]] = {}
    for owner_id, currency, total in db.execute(
        select(
            MetricsDaily.owner_id,
            MetricsDaily.currency,
            func.sum(MetricsDaily.spend_minor),
        )
        .where(
            MetricsDaily.owner_id.in_(ids),
            MetricsDaily.level == MetricLevel.ADSET,
            MetricsDaily.campaign_external_id.in_(every),
            MetricsDaily.date >= month.date(),
        )
        .group_by(MetricsDaily.owner_id, MetricsDaily.currency)
    ):
        spend.setdefault(owner_id, []).append((currency, int(total or 0)))
    leads = dict(
        db.execute(
            select(Lead.owner_id, func.count(Lead.id))
            .where(
                Lead.owner_id.in_(ids),
                Lead.is_test.is_(False),
                Lead.campaign_external_id.in_(every),
                Lead.submitted_at >= month,
            )
            .group_by(Lead.owner_id)
        ).all()
    )
    return {
        owner_id: _Activity(
            running=int(running.get(owner_id, 0)),
            spend=tuple(sorted(spend.get(owner_id, []), key=lambda pair: -pair[1])),
            leads=int(leads.get(owner_id, 0)),
        )
        for owner_id in launched
    }


def _pages(
    db: Session,
    ids: list[uuid.UUID],
    *,
    live: dict[uuid.UUID, Subscription],
    now: datetime,
) -> dict[uuid.UUID, PageCount]:
    """Pages switched on against the slots: plan pages, granted and bought.

    An Instagram account beyond a page's own takes a slot of its own.
    """
    used: Counter[uuid.UUID] = Counter(
        dict(
            db.execute(
                select(PageAccount.owner_id, func.count(PageAccount.id))
                .where(PageAccount.owner_id.in_(ids), PageAccount.is_active.is_(True))
                .group_by(PageAccount.owner_id)
            ).all()
        )
    )
    used.update(
        dict(
            db.execute(
                select(PageInstagram.owner_id, func.count(PageInstagram.id))
                .join(PageAccount, PageAccount.id == PageInstagram.page_id)
                .where(
                    PageInstagram.owner_id.in_(ids),
                    PageInstagram.is_active.is_(True),
                    PageAccount.is_active.is_(True),
                    PageInstagram.instagram_user_id != PageAccount.instagram_user_id,
                )
                .group_by(PageInstagram.owner_id)
            ).all()
        )
    )
    bought = dict(
        db.execute(
            select(Invoice.owner_id, func.sum(Invoice.pages))
            .where(
                Invoice.owner_id.in_(list(live)),
                Invoice.status == InvoiceStatus.PAID,
                Invoice.pages > 0,
                Invoice.pages_from <= now,
                Invoice.pages_until > now,
            )
            .group_by(Invoice.owner_id)
        ).all()
    )
    counts: dict[uuid.UUID, PageCount] = {}
    for owner in ids:
        subscription = live.get(owner)
        allowed = (
            subscription.plan.included_pages
            + subscription.extra_pages
            + int(bought.get(owner) or 0)
            if subscription is not None
            else None
        )
        counts[owner] = PageCount(used=int(used.get(owner) or 0), allowed=allowed)
    return counts


def _paid_totals(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, Money]:
    """Money each account has paid, per currency; Hamyon's share is not money."""
    found: dict[uuid.UUID, list[tuple[str, int]]] = {}
    for owner_id, currency, total in db.execute(
        select(Invoice.owner_id, Invoice.currency, func.sum(Invoice.amount_minor))
        .where(Invoice.owner_id.in_(ids), Invoice.status == InvoiceStatus.PAID)
        .group_by(Invoice.owner_id, Invoice.currency)
    ):
        if owner_id is not None and total:
            found.setdefault(owner_id, []).append((currency, int(total)))
    return {
        owner: tuple(sorted(pairs, key=lambda pair: -pair[1]))
        for owner, pairs in found.items()
    }


def _paid_before(db: Session, emails: Iterable[str]) -> set[str]:
    """Which of these addresses a deleted account paid from - lower-cased."""
    wanted = {email.lower() for email in emails if email}
    if not wanted:
        return set()
    return set(
        db.scalars(
            select(func.lower(Invoice.former_email)).where(
                Invoice.owner_id.is_(None), func.lower(Invoice.former_email).in_(wanted)
            )
        )
    )


def _managers(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, User]:
    found: dict[uuid.UUID, User] = {}
    for claim in db.scalars(
        select(SalesClaim)
        .options(joinedload(SalesClaim.manager))
        .where(
            SalesClaim.owner_id.in_(ids),
            SalesClaim.closed_at.is_(None),
            SalesClaim.manager_id.is_not(None),
        )
        .order_by(SalesClaim.claimed_at.desc())
    ):
        if claim.owner_id is not None and claim.manager is not None:
            found.setdefault(claim.owner_id, claim.manager)
    return found


def customer_page(
    db: Session,
    *,
    now: datetime,
    narrowing: Narrowing | None = None,
    offset: int = 0,
    as_of: datetime | None = None,
) -> CustomerPage:
    """One screenful of customers.

    ``as_of`` is the first screenful's ``now``, handed back by "load more", so
    whoever registers meanwhile does not push a row onto the next page twice.
    """
    as_of = as_of or now
    narrowing = narrowing or Narrowing()
    worst = worst_by_owner(db, now=now)
    accounts = narrowed_accounts(
        db, narrowing, now=now, as_of=as_of, troubled=set(worst)
    )
    total = int(
        db.scalar(select(func.count()).select_from(accounts.order_by(None).subquery()))
        or 0
    )
    people = list(db.scalars(accounts.offset(offset).limit(PAGE_SIZE)))
    ids = [person.id for person in people]

    profiles = _profiles(db, ids)
    live, ended = _subscriptions(db, ids, now=now)
    doing = _activity(db, ids, now=now)
    slots = _pages(db, ids, live=live, now=now)
    paid = _paid_totals(db, ids)
    returning = _paid_before(db, [person.email for person in people])
    managers = _managers(db, ids)
    quiet = _Activity()

    rows = []
    for person in people:
        subscription = live.get(person.id)
        stopped = ended.get(person.id)
        activity = doing.get(person.id, quiet)
        rows.append(
            CustomerRow(
                user=person,
                business=profiles.get(person.id),
                subscription=subscription,
                days_left=(
                    days_left(expires_at=subscription.expires_at, now=now)
                    if subscription is not None
                    else None
                ),
                ended=stopped,
                ended_on=(stopped.ended_at or stopped.expires_at) if stopped else None,
                trouble=worst.get(person.id),
                pages=slots.get(person.id),
                running=activity.running,
                spend=activity.spend,
                leads=activity.leads,
                paid_total=paid.get(person.id, ()),
                paid_before=person.email.lower() in returning,
                manager=managers.get(person.id),
            )
        )
    return CustomerPage(
        rows=tuple(rows),
        total=total,
        offset=offset,
        has_more=offset + len(rows) < total,
        as_of=as_of,
    )
