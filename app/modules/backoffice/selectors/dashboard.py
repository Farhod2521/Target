"""What the office's first screen reads.

One window of days for the whole screen - today, a week, thirty days, this
month, this year, or a stretch typed in - and against it: the money, the
customers, what the platform did, what waits on a person, what is wrong,
and who just paid. Money is read only for the roles that may see it.

Every day is the office's day: a window starts at midnight where the office
is, not where the server is. Money is counted in the currency most of the
window's bills are in; a bill in another one is not summed into it.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from llmkit import MICROS_PER_MINOR
from metaads.writing import is_dry_run_id
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.common.config import settings
from app.common.dates import localtime, office_zone
from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import NOT_RUNNING, LaunchStatus, LaunchStep
from app.modules.ads.models import Campaign, CampaignLaunch
from app.modules.audit.models import LLMCall
from app.modules.audit.selectors import exact_cost
from app.modules.backoffice.constants import (
    EXPIRING_DAYS,
    GRANT_KINDS,
    STUCK_HOLD_HOURS,
)
from app.modules.backoffice.models import StaffAction
from app.modules.billing.constants import (
    INVOICE_KIND_LABELS,
    LIVE_SUBSCRIPTION_STATUSES,
    InvoiceKind,
    InvoiceStatus,
    SubscriptionStatus,
)
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.billing.selectors import entitled_owner_ids, held_transactions
from app.modules.integrations.constants import ConnectionStatus
from app.modules.integrations.models import ProviderConnection
from app.modules.leads.models import Lead
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.sales.constants import Outcome
from app.modules.sales.models import SalesClaim
from app.modules.supportchat.models import SupportConversation
from app.modules.supportchat.selectors.conversations import AWAITING_OFFICE

PERIODS: tuple[tuple[str, str], ...] = (
    ("today", "Bugun"),
    ("7", "7 kun"),
    ("30", "30 kun"),
    ("month", "Shu oy"),
    ("year", "Shu yil"),
    ("range", "Oraliq"),
)
DEFAULT_PERIOD = "30"
DAY, WEEK, MONTH = "day", "week", "month"
# A typed stretch's bar size, by its length in days, and the longest read.
DAILY_UP_TO = 62
WEEKLY_UP_TO = 182
LONGEST_DAYS = 3660
RECENT_PAYMENTS = 10
MONTH_LABELS = (
    "Yan", "Fev", "Mar", "Apr", "May", "Iyn",
    "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek",
)  # fmt: skip


# -- the window ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Window:
    """First and last day, both counted, and the size of one bar."""

    period: str
    unit: str
    start: date
    end: date
    refused: str = ""

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def since(self) -> datetime:
        return datetime.combine(self.start, time.min, office_zone())

    @property
    def until(self) -> datetime:
        return datetime.combine(self.end + timedelta(days=1), time.min, office_zone())

    def before(self) -> "Window":
        """The same number of days, just before this one: what it is compared to."""
        end = self.start - timedelta(days=1)
        return Window(
            period=self.period,
            unit=self.unit,
            start=end - timedelta(days=self.days - 1),
            end=end,
        )

    def bar_of(self, day: date) -> date:
        if self.unit == WEEK:
            return day - timedelta(days=day.weekday())
        if self.unit == MONTH:
            return day.replace(day=1)
        return day

    def bar_end(self, start: date) -> date:
        if self.unit == WEEK:
            return start + timedelta(days=6)
        if self.unit == MONTH:
            following = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            return following - timedelta(days=1)
        return start

    def bars(self) -> list[date]:
        out: list[date] = []
        cursor = self.bar_of(self.start)
        while cursor <= self.end:
            out.append(cursor)
            cursor = self.bar_end(cursor) + timedelta(days=1)
        return out


def asked_window(
    *, period: str, since: date | None, until: date | None, today: date
) -> Window:
    """The window asked for, or thirty days when it asks nonsense."""
    if period == "range":
        return _typed(since=since, until=until, today=today)
    if period == "today":
        return Window(period=period, unit=DAY, start=today, end=today)
    if period == "7":
        return Window(
            period=period, unit=DAY, start=today - timedelta(days=6), end=today
        )
    if period == "month":
        return Window(period=period, unit=DAY, start=today.replace(day=1), end=today)
    if period == "year":
        return Window(
            period=period, unit=MONTH, start=today.replace(month=1, day=1), end=today
        )
    return Window(
        period=DEFAULT_PERIOD, unit=DAY, start=today - timedelta(days=29), end=today
    )


def _typed(*, since: date | None, until: date | None, today: date) -> Window:
    if since is None or until is None:
        return _refused(today, "Ikkala sanani ham tanlang.")
    first, last = sorted((since, until))
    if first > today:
        return _refused(today, "Bu kunlar hali kelmagan.")
    last = min(last, today)
    first = max(first, last - timedelta(days=LONGEST_DAYS))
    span = (last - first).days + 1
    unit = DAY if span <= DAILY_UP_TO else WEEK if span <= WEEKLY_UP_TO else MONTH
    return Window(period="range", unit=unit, start=first, end=last)


def _refused(today: date, reason: str) -> Window:
    shown = asked_window(period=DEFAULT_PERIOD, since=None, until=None, today=today)
    return Window(
        period="range",
        unit=shown.unit,
        start=shown.start,
        end=shown.end,
        refused=reason,
    )


def bar_label(start: date, unit: str) -> str:
    if unit == MONTH:
        return MONTH_LABELS[start.month - 1]
    return start.strftime("%d.%m")


def bar_hint(start: date, window: Window) -> str:
    if window.unit == WEEK:
        return f"{start:%d.%m} - {window.bar_end(start):%d.%m.%Y}"
    if window.unit == MONTH:
        return f"{MONTH_LABELS[start.month - 1]} {start.year}"
    return f"{start:%d.%m.%Y}"


def _customers() -> ColumnElement[bool]:
    """Accounts that are customers: not staff, not a CRM manager's login."""
    return and_(User.is_staff.is_(False), User.crm_owner_id.is_(None))


def _change(now: int, before: int) -> int | None:
    """Percent moved against the window before; none from nothing."""
    if not before:
        return None
    return round((now - before) * 100 / before)


# -- money -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanShare:
    name: str
    payments: int
    amount_minor: int
    share_pct: int


@dataclass(frozen=True, slots=True)
class Slice:
    amount_minor: int
    payments: int
    signups: int
    average_minor: int
    online_minor: int
    manual_minor: int
    plans: tuple[PlanShare, ...]


@dataclass(frozen=True, slots=True)
class Bar:
    key: str
    label: str
    hint: str
    height_pct: int
    is_current: bool
    figures: Slice


@dataclass(frozen=True, slots=True)
class Takings:
    window: Window
    currency: str
    bars: tuple[Bar, ...]
    whole: Slice
    before_minor: int
    change_pct: int | None
    unpaid: int
    unpaid_minor: int
    given_free: int


@dataclass(frozen=True, slots=True)
class _Paid:
    day: date
    plan: str
    amount_minor: int
    manual: bool
    currency: str


def _paid(db: Session, *, since: datetime, until: datetime) -> list[_Paid]:
    """Bills that brought money or balance in. A bill a promo took to nothing
    is a gift, not a sale; a pages or seats bill sold slots, not its plan."""
    rows = db.execute(
        select(
            Invoice.paid_at,
            Invoice.kind,
            Plan.name,
            Invoice.amount_minor,
            Invoice.manual_method,
            Invoice.currency,
        )
        .join(Plan, Plan.id == Invoice.plan_id)
        .where(
            Invoice.status == InvoiceStatus.PAID,
            Invoice.paid_at >= since,
            Invoice.paid_at < until,
            or_(Invoice.amount_minor != 0, Invoice.wallet_minor != 0),
        )
    )
    return [
        _Paid(
            day=localtime(paid_at).date() if paid_at else date.min,
            plan=(
                str(INVOICE_KIND_LABELS[InvoiceKind(kind)])
                if kind in (InvoiceKind.PAGES, InvoiceKind.SEATS)
                else name
            ),
            amount_minor=int(amount),
            manual=bool(manual),
            currency=currency,
        )
        for paid_at, kind, name, amount, manual, currency in rows
    ]


def main_currency(found: list[str]) -> str:
    """The currency most bills were paid in; the price list's when none were.
    A bill in another one is not summed into it."""
    if not found:
        return settings.billing_currency
    return Counter(found).most_common(1)[0][0]


def _signup_days(db: Session, *, since: datetime, until: datetime) -> list[date]:
    joined = db.scalars(
        select(User.date_joined).where(
            _customers(), User.date_joined >= since, User.date_joined < until
        )
    )
    return [localtime(moment).date() for moment in joined]


def _slice(rows: list[_Paid], signups: int) -> Slice:
    per_plan: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        per_plan[row.plan][0] += 1
        per_plan[row.plan][1] += row.amount_minor
    payments = len(rows)
    amount = sum(row.amount_minor for row in rows)
    manual = sum(row.amount_minor for row in rows if row.manual)
    return Slice(
        amount_minor=amount,
        payments=payments,
        signups=signups,
        average_minor=amount // payments if payments else 0,
        online_minor=amount - manual,
        manual_minor=manual,
        plans=tuple(
            PlanShare(
                name=name,
                payments=count,
                amount_minor=total,
                share_pct=round(total * 100 / amount) if amount else 0,
            )
            for name, (count, total) in sorted(
                per_plan.items(), key=lambda item: (-item[1][1], item[0])
            )
        ),
    )


def takings(db: Session, *, window: Window, today: date) -> Takings:
    """The money card: bars over the window, the whole, and what is owed."""
    every = _paid(db, since=window.since, until=window.until)
    currency = main_currency([row.currency for row in every])
    paid = [row for row in every if row.currency == currency]
    signups = Counter(
        window.bar_of(day)
        for day in _signup_days(db, since=window.since, until=window.until)
    )
    by_bar: dict[date, list[_Paid]] = defaultdict(list)
    for row in paid:
        by_bar[window.bar_of(row.day)].append(row)
    slices = {start: _slice(by_bar[start], signups[start]) for start in window.bars()}
    tallest = max((part.amount_minor for part in slices.values()), default=0)
    earlier = window.before()
    before = sum(
        row.amount_minor
        for row in _paid(db, since=earlier.since, until=earlier.until)
        if row.currency == currency
    )
    whole = _slice(paid, sum(signups.values()))
    unpaid_count, unpaid_sum = db.execute(
        select(
            func.count(Invoice.id), func.coalesce(func.sum(Invoice.amount_minor), 0)
        ).where(
            Invoice.status.in_((InvoiceStatus.PENDING, InvoiceStatus.HELD)),
            Invoice.currency == currency,
        )
    ).one()
    free = db.scalar(
        select(func.count(StaffAction.id)).where(
            StaffAction.kind.in_([str(kind) for kind in GRANT_KINDS]),
            StaffAction.created_at >= window.since,
            StaffAction.created_at < window.until,
            # A paid grant's journal row names its bill; a free one does not.
            StaffAction.detail["invoice"].is_(None),
        )
    )
    return Takings(
        window=window,
        currency=currency,
        bars=tuple(
            Bar(
                key=start.isoformat(),
                label=bar_label(start, window.unit),
                hint=bar_hint(start, window),
                height_pct=round(part.amount_minor * 100 / tallest) if tallest else 0,
                is_current=start <= today <= window.bar_end(start),
                figures=part,
            )
            for start, part in slices.items()
        ),
        whole=whole,
        before_minor=before,
        change_pct=_change(whole.amount_minor, before),
        unpaid=int(unpaid_count or 0),
        unpaid_minor=int(unpaid_sum or 0),
        given_free=int(free or 0),
    )


@dataclass(frozen=True, slots=True)
class PaymentRow:
    paid_at: datetime
    customer: User | None
    email: str
    plan: str
    amount_minor: int
    currency: str
    manual: bool


def recent_payments(db: Session) -> tuple[PaymentRow, ...]:
    """The last payments, newest first, with who paid and for what."""
    rows = db.scalars(
        select(Invoice)
        .options(joinedload(Invoice.owner), joinedload(Invoice.plan))
        .where(
            Invoice.status == InvoiceStatus.PAID,
            Invoice.paid_at.is_not(None),
            or_(Invoice.amount_minor != 0, Invoice.wallet_minor != 0),
        )
        .order_by(Invoice.paid_at.desc())
        .limit(RECENT_PAYMENTS)
    )
    return tuple(
        PaymentRow(
            paid_at=row.paid_at,
            customer=row.owner,
            email=row.owner.email if row.owner else row.former_email,
            plan=(
                str(INVOICE_KIND_LABELS[InvoiceKind(row.kind)])
                if row.kind in (InvoiceKind.PAGES, InvoiceKind.SEATS)
                else row.plan.name
            ),
            amount_minor=row.amount_minor,
            currency=row.currency,
            manual=bool(row.manual_method),
        )
        for row in rows
        if row.paid_at is not None
    )


# -- customers -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Customers:
    total: int
    joined: int
    joined_before: int
    joined_change_pct: int | None
    trial: int
    paying: int
    expiring: int
    churned: int
    joined_paid: int
    conversion_pct: int | None
    setup_unfinished: int
    meta_missing: int


def customers(db: Session, *, window: Window, now: datetime) -> Customers:
    """How many there are, how many came, stayed, paid and left."""

    def count(*where: ColumnElement[bool]) -> int:
        return int(
            db.scalar(select(func.count(User.id)).where(_customers(), *where)) or 0
        )

    def joined_in(frame: Window) -> ColumnElement[bool]:
        return and_(User.date_joined >= frame.since, User.date_joined < frame.until)

    def living(status: str) -> ColumnElement[bool]:
        return User.id.in_(
            select(Subscription.owner_id).where(
                Subscription.status == status, Subscription.expires_at > now
            )
        )

    live = select(Subscription.owner_id).where(
        Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
        Subscription.expires_at > now,
    )
    stopped = func.coalesce(Subscription.ended_at, Subscription.expires_at)
    churned = select(Subscription.owner_id).where(
        stopped >= window.since, stopped < min(window.until, now)
    )
    paid = select(Invoice.owner_id).where(
        Invoice.status == InvoiceStatus.PAID,
        Invoice.kind == InvoiceKind.PLAN,
        Invoice.amount_minor > 0,
    )
    connected = select(ProviderConnection.owner_id).where(
        ProviderConnection.status == ConnectionStatus.ACTIVE
    )
    unfinished = select(Subscription.owner_id).where(
        Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
        Subscription.expires_at > now,
        Subscription.setup_completed_at.is_(None),
    )
    joined = count(joined_in(window))
    joined_before = count(joined_in(window.before()))
    joined_paid = count(joined_in(window), User.id.in_(paid))
    return Customers(
        total=count(),
        joined=joined,
        joined_before=joined_before,
        joined_change_pct=_change(joined, joined_before),
        trial=count(living(SubscriptionStatus.TRIAL)),
        paying=count(living(SubscriptionStatus.ACTIVE)),
        expiring=count(
            User.id.in_(
                select(Subscription.owner_id).where(
                    Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
                    Subscription.expires_at >= now,
                    Subscription.expires_at < now + timedelta(days=EXPIRING_DAYS),
                )
            )
        ),
        churned=count(
            User.id.in_(churned), User.id.not_in(entitled_owner_ids(now=now))
        ),
        joined_paid=joined_paid,
        conversion_pct=round(joined_paid * 100 / joined) if joined else None,
        setup_unfinished=count(User.id.in_(unfinished)),
        meta_missing=count(User.id.in_(live), User.id.not_in(connected)),
    )


# -- the platform ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Activity:
    running: int
    launched: int
    failed: int
    spend: tuple[tuple[str, int], ...]
    leads: int
    leads_before: int
    leads_change_pct: int | None
    ai_cost_minor: int
    ai_currency: str


def _launched_campaigns(db: Session) -> set[str]:
    """Campaigns this product made; one built in Ads Manager is the
    customer's own business and no figure here counts it."""
    found: set[str] = set()
    for refs in db.scalars(select(CampaignLaunch.created_refs)):
        for campaign in ref_field.ref_ids(refs or {}, LaunchStep.CAMPAIGN):
            if campaign and not is_dry_run_id(campaign):
                found.add(campaign)
    return found


def activity(db: Session, *, window: Window) -> Activity:
    """What the platform did in the window, as its customers saw it."""
    campaigns = _launched_campaigns(db)
    staff = select(User.id).where(User.is_staff.is_(True))

    def launches(status: str) -> int:
        return int(
            db.scalar(
                select(func.count(CampaignLaunch.id)).where(
                    CampaignLaunch.status == status,
                    CampaignLaunch.finished_at >= window.since,
                    CampaignLaunch.finished_at < window.until,
                    CampaignLaunch.owner_id.not_in(staff),
                )
            )
            or 0
        )

    def leads_in(frame: Window) -> int:
        if not campaigns:
            return 0
        return int(
            db.scalar(
                select(func.count(Lead.id)).where(
                    Lead.is_test.is_(False),
                    Lead.campaign_external_id.in_(campaigns),
                    Lead.submitted_at >= frame.since,
                    Lead.submitted_at < frame.until,
                    Lead.owner_id.not_in(staff),
                )
            )
            or 0
        )

    running = (
        int(
            db.scalar(
                select(func.count(Campaign.id)).where(
                    Campaign.external_id.in_(campaigns),
                    Campaign.delivery.not_in(NOT_RUNNING),
                    Campaign.owner_id.not_in(staff),
                )
            )
            or 0
        )
        if campaigns
        else 0
    )
    spend = (
        [
            (currency, int(total or 0))
            for currency, total in db.execute(
                select(MetricsDaily.currency, func.sum(MetricsDaily.spend_minor))
                .where(
                    MetricsDaily.level == MetricLevel.ADSET,
                    MetricsDaily.campaign_external_id.in_(campaigns),
                    MetricsDaily.date >= window.start,
                    MetricsDaily.date <= window.end,
                    MetricsDaily.owner_id.not_in(staff),
                )
                .group_by(MetricsDaily.currency)
            )
            if total
        ]
        if campaigns
        else []
    )
    ai = db.scalar(
        select(func.coalesce(func.sum(exact_cost()), 0)).where(
            LLMCall.created_at >= window.since, LLMCall.created_at < window.until
        )
    )
    leads, leads_before = leads_in(window), leads_in(window.before())
    return Activity(
        running=running,
        launched=launches(LaunchStatus.CREATED),
        failed=launches(LaunchStatus.FAILED),
        spend=tuple(sorted(spend, key=lambda pair: -pair[1])),
        leads=leads,
        leads_before=leads_before,
        leads_change_pct=_change(leads, leads_before),
        ai_cost_minor=int(ai or 0) // MICROS_PER_MINOR,
        ai_currency=settings.anthropic_price_currency,
    )


# -- what waits ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Waiting:
    promos: int
    support: int
    support_oldest: datetime | None
    asks: int
    feedback: int
    arizas: int
    holds: int


def waiting(db: Session, *, now: datetime) -> Waiting:
    from app.modules.backoffice.selectors import (
        waiting_ask_count,
        waiting_feedback_count,
        waiting_promo_count,
    )
    from app.modules.sales.selectors import waiting_ariza_count

    support, oldest = db.execute(
        select(
            func.count(SupportConversation.id),
            func.min(SupportConversation.last_client_at),
        ).where(AWAITING_OFFICE)
    ).one()
    return Waiting(
        promos=waiting_promo_count(db),
        support=int(support or 0),
        support_oldest=oldest,
        asks=waiting_ask_count(db),
        feedback=waiting_feedback_count(db),
        arizas=waiting_ariza_count(db, now=now),
        holds=len(
            held_transactions(db, cutoff=now - timedelta(hours=STUCK_HOLD_HOURS))
        ),
    )


# -- sales -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ManagerSales:
    manager: User
    sold: int
    open: int


def sales(db: Session, *, window: Window) -> tuple[ManagerSales, ...]:
    """Per manager: sold in the window, and cards still open now."""
    sold = dict(
        db.execute(
            select(SalesClaim.manager_id, func.count(SalesClaim.id))
            .where(
                SalesClaim.outcome == Outcome.SOLD,
                SalesClaim.closed_at >= window.since,
                SalesClaim.closed_at < window.until,
                SalesClaim.manager_id.is_not(None),
            )
            .group_by(SalesClaim.manager_id)
        ).all()
    )
    still_open = dict(
        db.execute(
            select(SalesClaim.manager_id, func.count(SalesClaim.id))
            .where(SalesClaim.closed_at.is_(None), SalesClaim.manager_id.is_not(None))
            .group_by(SalesClaim.manager_id)
        ).all()
    )
    ids = {found for found in (*sold, *still_open) if found is not None}
    if not ids:
        return ()
    people = {
        user.id: user for user in db.scalars(select(User).where(User.id.in_(ids)))
    }
    rows = [
        ManagerSales(
            manager=people[manager_id],
            sold=int(sold.get(manager_id, 0)),
            open=int(still_open.get(manager_id, 0)),
        )
        for manager_id in ids
        if manager_id in people
    ]
    return tuple(sorted(rows, key=lambda row: (-row.sold, -row.open)))
