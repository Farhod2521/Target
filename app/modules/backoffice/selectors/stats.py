"""What the office's Statistika screen reads.

The dashboard answers "what needs a person now"; this answers "how is the
business going": who bought which plan and how often, who climbs from Start
to Standart and where the rest stop, what the assistant costs per customer,
and who the customers are.

Every figure counts customers only: not staff, not a CRM manager's login.
A bill whose customer has since been deleted still counts, by its email.

No figure is read per customer. Every paid plan bill is read in one query
and walked in memory (there are thousands, not millions); every other block
is one grouped query, or a few set queries over a subquery.
"""

import statistics
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from llmkit import MICROS_PER_MINOR
from metaads import PROVIDER as META
from metaads.writing import is_dry_run_id
from sqlalchemy import ColumnElement, Select, and_, case, distinct, func, or_, select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.dates import localtime
from app.modules.accounts.constants import ROLE_LABELS, SIGNUP_VIA_LABELS
from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import LaunchStatus, LaunchStep
from app.modules.ads.models import (
    AdSet,
    Campaign,
    CampaignLaunch,
    ChatTemplate,
    GoogleLaunch,
)
from app.modules.audit.constants import LLM_PURPOSE_LABELS
from app.modules.audit.models import LLMCall
from app.modules.audit.selectors import exact_cost
from app.modules.autopay.constants import CardStatus
from app.modules.autopay.models import SavedCard
from app.modules.backoffice.selectors.dashboard import (
    MONTH_LABELS,
    Window,
    bar_hint,
    bar_label,
    main_currency,
)
from app.modules.billing.constants import (
    AFTER_START_PLAN_CODE,
    DEFAULT_PLAN_CODE,
    LIVE_SUBSCRIPTION_STATUSES,
    InvoiceKind,
    InvoiceStatus,
    RedemptionStatus,
    SubscriptionStatus,
    TransactionState,
)
from app.modules.billing.models import (
    Invoice,
    PaymentTransaction,
    Plan,
    PromoRedemption,
    Subscription,
)
from app.modules.businesses.models import Business, BusinessCategory, CustomCategory
from app.modules.content_studio.models import Montage
from app.modules.crm.models import CrmSetup
from app.modules.destinations.models import FormSheet, LeadChat
from app.modules.integrations.models import ProviderConnection
from app.modules.integrations.selectors.demo import not_demo
from app.modules.leads.constants import MANUAL_PROVIDER
from app.modules.leads.models import Lead
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.results import screen_kind
from app.modules.referrals.models import ReferralBinding, ReferralReward
from app.modules.telephony.models import PhoneConnection
from core.metrics import formulas
from core.metrics.outcomes import campaign_goal

START_CODE = DEFAULT_PLAN_CODE
STANDARD_CODE = AFTER_START_PLAN_CODE
# Plans above Standart: one bill of these is already the top of the ladder.
UPPER_PLAN_CODES: tuple[str, ...] = ("pro", "enterprise")
# "Doimiy": the same plan bought this many times in a row (user, 2026-11-19).
LOYAL_RUN = 3
TOP = 10
COHORT_MONTHS = 6
COHORT_STEPS = 6
STEP_DAYS = 30
# Renewed this late is still "kept", not "lost and came back".
RENEW_GRACE = timedelta(days=3)
USD_MICROS = MICROS_PER_MINOR * 100  # micros of a cent, a hundred cents a dollar

RED, YELLOW, GREEN, GREY = "red", "yellow", "green", "other"
LADDER_LABELS = {
    RED: "Faqat Start",
    YELLOW: "Standart 1 marta",
    GREEN: "Standart 2+ marta yoki Pro",
    GREY: "Boshqa tarif",
}
LOST_LABELS = {
    "deleted": "Hisobini o'chirgan",
    "meta": "Meta'ni ulamagan",
    "setup": "Tayyorgarlikni yakunlamagan",
    "launch": "Reklama chiqarmagan",
    "lead": "Reklama chiqargan, lid kelmagan",
    "tried": "Lid kelgan, hisob ochilgan, to'lov o'tmagan",
    "silent": "Lid kelgan, to'lashga urinmagan",
}
FUNNEL_STEPS = (
    ("joined", "Ro'yxatdan o'tdi"),
    ("profile", "Telefon va rolni kiritdi"),
    ("meta", "Meta'ni uladi"),
    ("setup", "Tayyorgarlikni yakunladi"),
    ("launch", "Birinchi reklamani chiqardi"),
    ("lead", "Birinchi lid keldi"),
    ("paid", "Birinchi to'lov"),
    ("standard", "Standart yoki yuqori tarif"),
    ("green", "Standart 2+ marta yoki Pro"),
)
NO_VALUE = "—"


def _customer() -> ColumnElement[bool]:
    return and_(
        User.is_staff.is_(False), User.crm_owner_id.is_(None), not_demo(User.id)
    )


def payer_key(owner: uuid.UUID | None, email: str | None) -> str:
    """A customer's key: their id, or a deleted account's email; empty when
    neither is known (such a bill is not counted per customer)."""
    if owner:
        return str(owner)
    found = (email or "").strip().lower()
    return f"email:{found}" if found else ""


def plan_part(amount: int, pages: int, seats: int) -> int:
    """The plan's share of a plan bill: a renewal carries its extra pages and
    manager seats on the same bill, and those are sold slots, not the plan."""
    return max(0, amount - min(amount, pages + seats))


def customer_ids() -> Select[tuple[uuid.UUID]]:
    return select(User.id).where(_customer())


def _pct(part: int, whole: int) -> float | None:
    """One decimal; none from nothing."""
    return round(part * 100 / whole, 1) if whole else None


def _median(values: Iterable[float]) -> float | None:
    found = list(values)
    return round(statistics.median(found), 1) if found else None


# -- every paid plan bill ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Purchase:
    key: str
    owner_id: uuid.UUID | None
    plan_id: uuid.UUID
    code: str
    name: str
    paid_at: datetime
    amount_minor: int
    currency: str
    days: int


@dataclass(slots=True)
class Buyer:
    """One customer's paid plan bills, oldest first."""

    key: str
    owner_id: uuid.UUID | None
    bills: list[Purchase] = field(default_factory=list)

    def upto(self, moment: datetime) -> list[Purchase]:
        return [bill for bill in self.bills if bill.paid_at < moment]


def purchases(db: Session) -> dict[str, Buyer]:
    """Every plan bill that brought money or balance in, by customer.

    A bill a promo took to nothing is a gift, not a sale; a pages or seats
    bill sold slots, not a plan; a refunded or archived bill sold nothing.
    """
    rows = db.execute(
        select(
            Invoice.owner_id,
            Invoice.former_email,
            Invoice.plan_id,
            Plan.code,
            Plan.name,
            Invoice.paid_at,
            Invoice.amount_minor,
            Invoice.pages_minor,
            Invoice.seats_minor,
            Invoice.currency,
            Invoice.applied_days,
            Invoice.period_days,
        )
        .join(Plan, Plan.id == Invoice.plan_id)
        .outerjoin(User, User.id == Invoice.owner_id)
        .where(
            Invoice.archived_at.is_(None),
            Invoice.status == InvoiceStatus.PAID,
            Invoice.kind == InvoiceKind.PLAN,
            Invoice.paid_at.is_not(None),
            or_(Invoice.amount_minor != 0, Invoice.wallet_minor != 0),
            or_(Invoice.owner_id.is_(None), _customer()),
        )
        .order_by(Invoice.paid_at, Invoice.id)
    )
    found: dict[str, Buyer] = {}
    for (
        owner,
        email,
        plan,
        code,
        name,
        paid,
        amount,
        pages,
        seats,
        currency,
        applied,
        period,
    ) in rows:
        key = payer_key(owner, email)
        if not key:
            continue
        buyer = found.setdefault(key, Buyer(key=key, owner_id=owner))
        buyer.bills.append(
            Purchase(
                key=key,
                owner_id=owner,
                plan_id=plan,
                code=code,
                name=name,
                paid_at=paid,
                amount_minor=plan_part(int(amount), int(pages), int(seats)),
                currency=currency,
                days=int(applied or period or STEP_DAYS),
            )
        )
    return found


@dataclass(frozen=True, slots=True)
class Climb:
    """When a customer reached each colour of the ladder, if they did."""

    red: datetime | None
    yellow: datetime | None
    green: datetime | None

    @property
    def colour(self) -> str:
        if self.green:
            return GREEN
        if self.yellow:
            return YELLOW
        if self.red:
            return RED
        return GREY

    @property
    def reached_at(self) -> datetime | None:
        return {GREEN: self.green, YELLOW: self.yellow, RED: self.red}.get(self.colour)


def climb(bills: list[Purchase]) -> Climb:
    red = yellow = green = None
    standards = 0
    for bill in bills:
        if bill.code == START_CODE and red is None:
            red = bill.paid_at
        elif bill.code == STANDARD_CODE:
            standards += 1
            if yellow is None:
                yellow = bill.paid_at
            if standards == 2 and green is None:
                green = bill.paid_at
        elif bill.code in UPPER_PLAN_CODES and green is None:
            green = bill.paid_at
    return Climb(red=red, yellow=yellow, green=green)


def longest_run(bills: list[Purchase]) -> tuple[int, Purchase | None]:
    """The longest stretch of the same plan bought back to back, and the bill
    that made it that long (the last of it)."""
    best, best_end, run = 0, None, 0
    previous: uuid.UUID | None = None
    for bill in bills:
        run = run + 1 if bill.plan_id == previous else 1
        previous = bill.plan_id
        if run >= best:
            best, best_end = run, bill
    return best, best_end


def covered_spans(bills: list[Purchase]) -> list[tuple[datetime, datetime]]:
    """The stretches a customer's bills paid for. A bill paid before the last
    ran out stacks on its end, as a renewal does; one paid up to
    ``RENEW_GRACE`` after it ran out continues the stretch, from the day it
    was paid. Days the office gave and trial days are not bills, so they are
    not here."""
    spans: list[tuple[datetime, datetime]] = []
    for bill in bills:
        start = bill.paid_at
        if spans and start <= spans[-1][1] + RENEW_GRACE:
            first, end = spans.pop()
            spans.append((first, max(end, start) + timedelta(days=bill.days)))
            continue
        spans.append((start, start + timedelta(days=bill.days)))
    return spans


def covered(spans: list[tuple[datetime, datetime]], moment: datetime) -> bool:
    return any(start <= moment < end for start, end in spans)


# -- the ladder and the plans ---------------------------------------------------


def ladder(buyers: dict[str, Buyer], *, window: Window) -> dict[str, Any]:
    """The pie: every customer who has paid, by how far up the plans they got,
    as of the window's end; and who got to their colour inside the window."""
    counts: Counter[str] = Counter()
    fresh: Counter[str] = Counter()
    yellow_from_start = 0
    for buyer in buyers.values():
        bills = buyer.upto(window.until)
        if not bills:
            continue
        step = climb(bills)
        counts[step.colour] += 1
        reached = step.reached_at
        if reached and window.since <= reached < window.until:
            fresh[step.colour] += 1
        if step.colour == YELLOW and step.red and step.red < (step.yellow or step.red):
            yellow_from_start += 1
    total = sum(counts.values())
    return {
        "total": total,
        "segments": [
            {
                "key": colour,
                "label": LADDER_LABELS[colour],
                "customers": counts[colour],
                "share_pct": _pct(counts[colour], total),
                "new_in_window": fresh[colour],
            }
            for colour in (RED, YELLOW, GREEN, GREY)
            if colour != GREY or counts[GREY]
        ],
        "yellow_from_start": yellow_from_start,
        "yellow_direct": counts[YELLOW] - yellow_from_start,
    }


def plans_sold(
    buyers: dict[str, Buyer], *, window: Window, plans: list[Plan]
) -> dict[str, Any]:
    """Per plan inside the window: who bought it, and was it their first,
    second or a later bill; then how many bills each customer has paid."""
    rows: dict[uuid.UUID, dict[str, Any]] = {}
    currencies: list[str] = []
    for buyer in buyers.values():
        previous: Purchase | None = None
        for order, bill in enumerate(buyer.bills, start=1):
            if window.since <= bill.paid_at < window.until:
                currencies.append(bill.currency)
                row = rows.setdefault(
                    bill.plan_id,
                    {
                        "buyers": set(),
                        "bills": 0,
                        "amounts": Counter(),
                        "first": 0,
                        "second": 0,
                        "later": 0,
                        "same_again": 0,
                    },
                )
                row["buyers"].add(buyer.key)
                row["bills"] += 1
                row["amounts"][bill.currency] += bill.amount_minor
                bucket = "first" if order == 1 else "second" if order == 2 else "later"
                row[bucket] += 1
                if previous is not None and previous.plan_id == bill.plan_id:
                    row["same_again"] += 1
            previous = bill
    currency = main_currency(currencies)
    by_id = {plan.id: plan for plan in plans}
    bills_total = sum(row["bills"] for row in rows.values())
    out = [
        {
            "plan_id": str(plan_id),
            "code": by_id[plan_id].code if plan_id in by_id else "",
            "name": by_id[plan_id].name if plan_id in by_id else NO_VALUE,
            "buyers": len(row["buyers"]),
            "bills": row["bills"],
            "share_pct": _pct(row["bills"], bills_total),
            "amount_minor": row["amounts"][currency],
            "first_time": row["first"],
            "second_time": row["second"],
            "third_or_later": row["later"],
            "same_plan_again": row["same_again"],
        }
        for plan_id, row in rows.items()
    ]
    out.sort(key=lambda row: (-row["amount_minor"], -row["bills"], row["name"]))

    times: Counter[str] = Counter()
    for buyer in buyers.values():
        made = len(buyer.upto(window.until))
        if made:
            times["1" if made == 1 else "2" if made == 2 else "3+"] += 1
    buyers_total = sum(times.values())
    return {
        "currency": currency,
        "rows": out,
        "bills": bills_total,
        "times": [
            {
                "key": key,
                "label": label,
                "customers": times[key],
                "share_pct": _pct(times[key], buyers_total),
            }
            for key, label in (
                ("1", "1 marta"),
                ("2", "2 marta"),
                ("3+", "3 va undan ko'p"),
            )
        ],
    }


def loyal(
    buyers: dict[str, Buyer],
    *,
    window: Window,
    live: set[uuid.UUID],
    plans: list[Plan],
) -> dict[str, Any]:
    """ "Doimiy": the same plan bought three times in a row, as of the window's
    end. ``still_live`` of them are entitled now."""
    names = {plan.id: plan.name for plan in plans}
    per_plan: Counter[uuid.UUID] = Counter()
    total = still_live = fresh = 0
    buyers_total = 0
    for buyer in buyers.values():
        bills = buyer.upto(window.until)
        if not bills:
            continue
        buyers_total += 1
        run, last = longest_run(bills)
        if run < LOYAL_RUN or last is None:
            continue
        total += 1
        per_plan[last.plan_id] += 1
        if buyer.owner_id in live:
            still_live += 1
        # The bill that made it the third in a row landed in the window.
        third = _third_in_row(bills)
        if third and window.since <= third < window.until:
            fresh += 1
    return {
        "customers": total,
        "share_pct": _pct(total, buyers_total),
        "still_live": still_live,
        "new_in_window": fresh,
        "run": LOYAL_RUN,
        "plans": [
            {"name": names.get(plan_id, NO_VALUE), "customers": count}
            for plan_id, count in per_plan.most_common()
        ],
    }


def _third_in_row(bills: list[Purchase]) -> datetime | None:
    run, previous = 0, None
    for bill in bills:
        run = run + 1 if bill.plan_id == previous else 1
        previous = bill.plan_id
        if run == LOYAL_RUN:
            return bill.paid_at
    return None


def keeping(
    buyers: dict[str, Buyer], *, window: Window, now: datetime
) -> dict[str, Any]:
    """Paid cover across the window: who it began with, who it lost, who
    came back after a gap; and of each month's first-time buyers, how many
    were still paid up 30, 60, ... days later."""
    end = min(window.until, now)
    at_start = at_end = lost = came_back = 0
    cohorts: dict[tuple[int, int], list[list[tuple[datetime, datetime]]]] = defaultdict(
        list
    )
    firsts: dict[tuple[int, int], list[datetime]] = defaultdict(list)
    for buyer in buyers.values():
        spans = covered_spans(buyer.bills)
        began = covered(spans, window.since)
        stays = covered(spans, end - timedelta(microseconds=1))
        at_start += began
        at_end += stays
        if began and not stays:
            lost += 1
        if any(window.since <= start < window.until for start, _ in spans[1:]):
            came_back += 1
        first = buyer.bills[0].paid_at
        month = localtime(first)
        key = (month.year, month.month)
        cohorts[key].append(spans)
        firsts[key].append(first)

    last = localtime(end - timedelta(microseconds=1))
    months: list[tuple[int, int]] = []
    year, month_no = last.year, last.month
    for _ in range(COHORT_MONTHS):
        months.append((year, month_no))
        year, month_no = (year, month_no - 1) if month_no > 1 else (year - 1, 12)
    months.reverse()
    rows = []
    for key in months:
        group = cohorts.get(key, [])
        started = firsts.get(key, [])
        steps: list[float | None] = []
        for step in range(1, COHORT_STEPS + 1):
            due = [
                spans
                for spans, first in zip(group, started, strict=True)
                if first + timedelta(days=STEP_DAYS * step) <= now
            ]
            kept = sum(
                covered(spans, first + timedelta(days=STEP_DAYS * step))
                for spans, first in zip(group, started, strict=True)
                if first + timedelta(days=STEP_DAYS * step) <= now
            )
            steps.append(_pct(kept, len(due)) if due else None)
        rows.append(
            {
                "month": f"{key[0]}-{key[1]:02d}",
                "label": f"{MONTH_LABELS[key[1] - 1]} {key[0]}",
                "customers": len(group),
                "kept_pct": steps,
            }
        )
    return {
        "paid_at_start": at_start,
        "paid_at_end": at_end,
        "lost": lost,
        "churn_pct": _pct(lost, at_start),
        "came_back": came_back,
        "cohort_step_days": STEP_DAYS,
        "cohorts": rows,
    }


# -- Start to Standart ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StartCohort:
    started: int
    in_start: int
    due: int
    moved: int
    moved_to: dict[str, int]
    days_to_move: list[float]
    lost: dict[str, list[uuid.UUID | None]]


def start_cohort(
    db: Session, buyers: dict[str, Buyer], *, window: Window, now: datetime
) -> StartCohort:
    """Customers whose first Start bill was paid inside the window: who has
    moved on to Standart or higher since, and for each one who has not and
    whose Start has run out, the first step they never made."""
    started = in_start = due = moved = 0
    moved_to: Counter[str] = Counter()
    days: list[float] = []
    stopped: list[tuple[uuid.UUID | None, datetime]] = []
    for buyer in buyers.values():
        start = next((b for b in buyer.bills if b.code == START_CODE), None)
        if start is None or not window.since <= start.paid_at < window.until:
            continue
        started += 1
        onward = next(
            (
                b
                for b in buyer.bills
                if b.paid_at > start.paid_at
                and (b.code == STANDARD_CODE or b.code in UPPER_PLAN_CODES)
            ),
            None,
        )
        if onward is not None:
            due += 1
            moved += 1
            moved_to[onward.name] += 1
            days.append((onward.paid_at - start.paid_at).total_seconds() / 86400)
            continue
        ran_out = covered_spans(buyer.bills)[-1][1]
        if ran_out > now:
            in_start += 1
            continue
        due += 1
        stopped.append((buyer.owner_id, start.paid_at))
    return StartCohort(
        started=started,
        in_start=in_start,
        due=due,
        moved=moved,
        moved_to=dict(moved_to),
        days_to_move=days,
        lost=_why_stopped(db, stopped),
    )


def _why_stopped(
    db: Session, stopped: list[tuple[uuid.UUID | None, datetime]]
) -> dict[str, list[uuid.UUID | None]]:
    """The first step each one never made, read in five set queries."""
    out: dict[str, list[uuid.UUID | None]] = {key: [] for key in LOST_LABELS}
    ids = [owner for owner, _ in stopped if owner is not None]
    for owner, _ in stopped:
        if owner is None:
            out["deleted"].append(None)
    if not ids:
        return out
    prepared = set(
        db.scalars(
            select(User.id).where(User.id.in_(ids), User.prepared_at.is_not(None))
        )
    )
    connected = set(
        db.scalars(
            select(ProviderConnection.owner_id)
            .distinct()
            .where(
                ProviderConnection.owner_id.in_(ids),
                ProviderConnection.provider == META,
            )
        )
    )
    launched = set(
        db.scalars(
            select(CampaignLaunch.owner_id)
            .distinct()
            .where(
                CampaignLaunch.owner_id.in_(ids),
                CampaignLaunch.status == LaunchStatus.CREATED,
            )
        )
    )
    with_leads = set(
        db.scalars(select(Lead.owner_id).distinct().where(Lead.owner_id.in_(ids)))
    )
    began = {owner: at for owner, at in stopped if owner is not None}
    # A plan bill opened after Start began and never paid: they tried.
    tried = {
        owner
        for owner, opened in db.execute(
            select(Invoice.owner_id, Invoice.created_at).where(
                Invoice.owner_id.in_(ids),
                Invoice.kind == InvoiceKind.PLAN,
                Invoice.status != InvoiceStatus.PAID,
            )
        )
        if owner in began and opened > began[owner]
    }
    for owner in ids:
        # Meta is let go of on "disconnect" and preparation with it, so an
        # account that launched did both, whatever the rows say today.
        if owner not in connected and owner not in launched:
            out["meta"].append(owner)
        elif owner not in prepared and owner not in launched:
            out["setup"].append(owner)
        elif owner not in launched:
            out["launch"].append(owner)
        elif owner not in with_leads:
            out["lead"].append(owner)
        elif owner in tried:
            out["tried"].append(owner)
        else:
            out["silent"].append(owner)
    return out


def start_out(found: StartCohort) -> dict[str, Any]:
    lost_total = sum(len(owners) for owners in found.lost.values())
    return {
        "started": found.started,
        "in_start": found.in_start,
        "due": found.due,
        "moved": found.moved,
        "moved_pct": _pct(found.moved, found.due),
        "moved_to": [
            {"name": name, "customers": count}
            for name, count in sorted(found.moved_to.items(), key=lambda i: -i[1])
        ],
        "median_days_to_move": _median(found.days_to_move),
        "lost": lost_total,
        "lost_reasons": [
            {
                "key": key,
                "label": label,
                "customers": len(found.lost[key]),
                "share_pct": _pct(len(found.lost[key]), lost_total),
            }
            for key, label in LOST_LABELS.items()
        ],
    }


# -- the path from signing up ----------------------------------------------------


def funnel(db: Session, buyers: dict[str, Buyer], *, window: Window) -> dict[str, Any]:
    """Customers who signed up inside the window, by the furthest step they
    reached. A later step counts the earlier ones as made, so each step's
    "dropped" is exactly the customers who stopped right before it."""
    joined = (
        select(User.id)
        .where(
            _customer(),
            User.date_joined >= window.since,
            User.date_joined < window.until,
        )
        .scalar_subquery()
    )
    people = db.execute(
        select(User.id, User.phone, User.role, User.prepared_at).where(
            User.id.in_(joined)
        )
    ).all()

    def owners(query: Select[tuple[uuid.UUID]]) -> set[uuid.UUID]:
        return set(db.scalars(query))

    connected = owners(
        select(ProviderConnection.owner_id)
        .distinct()
        .where(
            ProviderConnection.owner_id.in_(joined),
            ProviderConnection.provider == META,
        )
    )
    launched = owners(
        select(CampaignLaunch.owner_id)
        .distinct()
        .where(
            CampaignLaunch.owner_id.in_(joined),
            CampaignLaunch.status == LaunchStatus.CREATED,
        )
    )
    with_leads = owners(
        select(Lead.owner_id).distinct().where(Lead.owner_id.in_(joined))
    )
    reached: Counter[int] = Counter()
    for owner, phone, role, prepared in people:
        bills = buyers[str(owner)].bills if str(owner) in buyers else []
        colour = climb(bills).colour if bills else ""
        made = (
            True,
            bool(phone and role),
            owner in connected,
            prepared is not None,
            owner in launched,
            owner in with_leads,
            bool(bills),
            colour in (YELLOW, GREEN),
            colour == GREEN,
        )
        reached[max(step for step, done in enumerate(made) if done)] += 1
    total = len(people)
    rows = []
    previous = total
    for step, (key, label) in enumerate(FUNNEL_STEPS):
        count = sum(n for depth, n in reached.items() if depth >= step)
        rows.append(
            {
                "key": key,
                "label": label,
                "customers": count,
                "of_joined_pct": _pct(count, total),
                "of_previous_pct": _pct(count, previous),
                "dropped": previous - count,
            }
        )
        previous = count
    return {"joined": total, "steps": rows}


# -- how long each step takes --------------------------------------------------------

TIMED_STEPS = (
    ("meta", "Meta'ni uladi"),
    ("setup", "Tayyorgarlikni yakunladi"),
    ("paid", "Birinchi to'lov"),
    ("launch", "Birinchi reklamani chiqardi"),
    ("lead", "Birinchi lid keldi"),
)
# A step made within this many days of signing up, counted together.
WITHIN_DAYS = (1, 3, 7)


def first_moments(db: Session, owners: Any) -> dict[uuid.UUID, dict[str, datetime]]:
    """When each of ``owners`` (ids, or a query of ids) first made each timed
    step. Four grouped queries, whatever the number of customers.

    Meta's moment is the oldest connection still on record: one let go of
    and made again shows the later day.
    """
    found: dict[uuid.UUID, dict[str, datetime]] = defaultdict(dict)

    def keep(step: str, rows: Iterable[Any]) -> None:
        for owner, moment in rows:
            if owner is not None and moment is not None:
                found[owner][step] = moment

    keep(
        "setup",
        db.execute(
            select(User.id, User.prepared_at).where(
                User.id.in_(owners), User.prepared_at.is_not(None)
            )
        ),
    )
    keep(
        "meta",
        db.execute(
            select(ProviderConnection.owner_id, func.min(ProviderConnection.created_at))
            .where(
                ProviderConnection.owner_id.in_(owners),
                ProviderConnection.provider == META,
            )
            .group_by(ProviderConnection.owner_id)
        ),
    )
    keep(
        "paid",
        db.execute(
            select(Invoice.owner_id, func.min(Invoice.paid_at))
            .where(
                Invoice.owner_id.in_(owners),
                Invoice.archived_at.is_(None),
                Invoice.status == InvoiceStatus.PAID,
                Invoice.kind == InvoiceKind.PLAN,
                Invoice.paid_at.is_not(None),
                or_(Invoice.amount_minor != 0, Invoice.wallet_minor != 0),
            )
            .group_by(Invoice.owner_id)
        ),
    )
    keep(
        "launch",
        db.execute(
            select(CampaignLaunch.owner_id, func.min(CampaignLaunch.created_at))
            .where(
                CampaignLaunch.owner_id.in_(owners),
                CampaignLaunch.status == LaunchStatus.CREATED,
            )
            .group_by(CampaignLaunch.owner_id)
        ),
    )
    keep(
        "lead",
        db.execute(
            select(Lead.owner_id, func.min(Lead.created_at))
            .where(Lead.owner_id.in_(owners))
            .group_by(Lead.owner_id)
        ),
    )
    return dict(found)


def _days_between(start: datetime, end: datetime) -> float:
    """Never below nothing: a step dated before its start took no time."""
    return max((end - start).total_seconds(), 0.0) / 86400


def _spread(days: list[float], *, of: int) -> dict[str, Any]:
    """How long a step took for those who made it: the middle, the average,
    and how many made it within a day, three and a week."""
    return {
        "reached": len(days),
        "reached_pct": _pct(len(days), of),
        "median_days": _median(days),
        "average_days": round(sum(days) / len(days), 1) if days else None,
        "median_hours": round(statistics.median(days) * 24, 1) if days else None,
        "within": [
            {"days": limit, "customers": sum(1 for value in days if value <= limit)}
            for limit in WITHIN_DAYS
        ],
        "later": sum(1 for value in days if value > WITHIN_DAYS[-1]),
    }


def timings(db: Session, *, window: Window) -> dict[str, Any]:
    """Customers who signed up inside the window: how long after signing up
    each step was first made, and from the first payment to the first ad.

    Those who signed up lately have had less time, so a recent window
    under-counts the later steps.
    """
    joined = dict(
        db.execute(
            select(User.id, User.date_joined).where(
                _customer(),
                User.date_joined >= window.since,
                User.date_joined < window.until,
            )
        ).all()
    )
    moments = first_moments(
        db,
        select(User.id).where(
            _customer(),
            User.date_joined >= window.since,
            User.date_joined < window.until,
        ),
    )
    steps = []
    for key, label in TIMED_STEPS:
        days = [
            _days_between(joined[owner], made[key])
            for owner, made in moments.items()
            if key in made and owner in joined
        ]
        steps.append({"key": key, "label": label, **_spread(days, of=len(joined))})
    both = [
        made
        for owner, made in moments.items()
        if owner in joined and "paid" in made and "launch" in made
    ]
    after = [made for made in both if made["launch"] >= made["paid"]]
    return {
        "joined": len(joined),
        "steps": steps,
        "paid_then_launch": {
            "both": len(both),
            "launched_first": len(both) - len(after),
            **_spread(
                [_days_between(made["paid"], made["launch"]) for made in after],
                of=len(both),
            ),
        },
    }


# -- advertising by the kind of customer ---------------------------------------------

NO_BUSINESS = "unlinked"
SEGMENT_LABELS = {
    "custom": "O'zi yozgan",
    "none": "Tanlanmagan",
    NO_BUSINESS: "Biznesga bog'lanmagan",
}


def _directions_of_pages(db: Session) -> dict[uuid.UUID, tuple[str, str]]:
    """Each page's business direction, as (key, label)."""
    found: dict[uuid.UUID, tuple[str, str]] = {}
    for page, direction, custom, key, label in db.execute(
        select(
            Business.page_id,
            Business.direction_id,
            Business.custom_category_id,
            BusinessCategory.key,
            BusinessCategory.label_uz,
        )
        .outerjoin(BusinessCategory, BusinessCategory.id == Business.direction_id)
        .where(Business.page_id.is_not(None))
    ):
        if page is None:
            continue
        if direction is not None:
            found[page] = (str(key), str(label or key))
        elif custom is not None:
            found[page] = ("custom", SEGMENT_LABELS["custom"])
        else:
            found[page] = ("none", SEGMENT_LABELS["none"])
    return found


def _campaign_kinds(db: Session, owners: Any) -> dict[str, str]:
    """What one result of each campaign is ("lead", "site_lead", a message...),
    from the ad set that speaks for it - the rule the Reklama screen uses."""
    adsets: dict[str, list[tuple[str, str, Any]]] = defaultdict(list)
    for campaign, adset, goal, promoted in db.execute(
        select(
            Campaign.external_id,
            AdSet.external_id,
            AdSet.optimization_goal_raw,
            AdSet.promoted_object_raw,
        )
        .join(AdSet, AdSet.campaign_id == Campaign.id)
        .where(Campaign.owner_id.in_(owners))
    ):
        adsets[campaign].append(
            (adset, goal or "", promoted if isinstance(promoted, dict) else None)
        )
    return {
        campaign: str(screen_kind(*campaign_goal(rows)))
        for campaign, rows in adsets.items()
    }


def ads_by(db: Session, *, window: Window, by: str) -> dict[str, Any]:
    """Advertising inside the window, split by the business's direction
    (``by="direction"``) or by the customer's role (``by="role"``).

    Only campaigns this product launched, as on the dashboard. A campaign
    belongs to the direction of the business on the page it was launched
    for - a customer with several businesses is split between them; a
    launch whose page has no business stands apart. Spend is summed in the
    currency most of it is in; a campaign billed in another is left out
    and counted.

    The lead cost is the spend of the campaigns run for leads over those
    campaigns' leads: money spent for messages, visits or anything else
    bought no lead and is not laid on the leads' price. What a campaign is
    run for is read as the office's Reklama screen reads it - from the ad
    set that speaks for it, and a lead where the copy has no goal.
    """
    customers = customer_ids()
    if by == "role":
        labels = {str(key): str(label) for key, label in ROLE_LABELS.items()}
        roles = dict(db.execute(select(User.id, User.role).where(_customer())).all())
        pages: dict[uuid.UUID, tuple[str, str]] = {}
    else:
        labels, roles = {}, {}
        pages = _directions_of_pages(db)

    def segment(owner: uuid.UUID, page: uuid.UUID | None) -> tuple[str, str]:
        if by == "role":
            key = str(roles.get(owner) or "")
            return (key, labels.get(key, key)) if key else ("", NO_VALUE)
        if page is not None and page in pages:
            return pages[page]
        return NO_BUSINESS, SEGMENT_LABELS[NO_BUSINESS]

    rows: dict[str, dict[str, Any]] = {}

    def row(found: tuple[str, str]) -> dict[str, Any]:
        key, label = found
        return rows.setdefault(
            key,
            {
                "key": key,
                "label": label,
                "launched": 0,
                "failed": 0,
                "spend": Counter(),
                "lead_spend": Counter(),
                "leads": Counter(),
                "advertisers": defaultdict(set),
            },
        )

    campaigns: dict[str, tuple[str, str]] = {}
    for owner, page, status, finished, refs in db.execute(
        select(
            CampaignLaunch.owner_id,
            CampaignLaunch.page_id,
            CampaignLaunch.status,
            CampaignLaunch.finished_at,
            CampaignLaunch.created_refs,
        ).where(
            CampaignLaunch.owner_id.in_(customers),
            CampaignLaunch.status.in_((LaunchStatus.CREATED, LaunchStatus.FAILED)),
        )
    ):
        found = segment(owner, page)
        for campaign in ref_field.ref_ids(refs or {}, LaunchStep.CAMPAIGN):
            if campaign and not is_dry_run_id(campaign):
                campaigns[campaign] = found
        if finished is not None and window.since <= finished < window.until:
            bucket = "launched" if status == LaunchStatus.CREATED else "failed"
            row(found)[bucket] += 1

    kinds = _campaign_kinds(db, customers)

    def for_leads(campaign: str) -> bool:
        return kinds.get(campaign, "lead") == "lead"

    currency_of: dict[str, str] = {}
    for campaign, owner, currency, spend in db.execute(
        select(
            MetricsDaily.campaign_external_id,
            MetricsDaily.owner_id,
            MetricsDaily.currency,
            func.sum(MetricsDaily.spend_minor),
        )
        .where(
            MetricsDaily.level == MetricLevel.ADSET,
            MetricsDaily.date >= window.start,
            MetricsDaily.date <= window.end,
            MetricsDaily.owner_id.in_(customers),
        )
        .group_by(
            MetricsDaily.campaign_external_id,
            MetricsDaily.owner_id,
            MetricsDaily.currency,
        )
    ):
        if campaign in campaigns and spend:
            found_row = row(campaigns[campaign])
            found_row["spend"][currency] += int(spend)
            if for_leads(campaign):
                found_row["lead_spend"][currency] += int(spend)
            found_row["advertisers"][currency].add(owner)
            currency_of[campaign] = currency
    spent: Counter[str] = Counter()
    for found_row in rows.values():
        spent.update(found_row["spend"])
    currency = spent.most_common(1)[0][0] if spent else ""
    for campaign, count in db.execute(
        select(Lead.campaign_external_id, func.count(Lead.id))
        .where(
            Lead.is_test.is_(False),
            Lead.campaign_external_id != "",
            Lead.submitted_at >= window.since,
            Lead.submitted_at < window.until,
            Lead.owner_id.in_(customers),
        )
        .group_by(Lead.campaign_external_id)
    ):
        if campaign in campaigns and for_leads(campaign):
            row(campaigns[campaign])["leads"][currency_of.get(campaign, currency)] += (
                int(count)
            )

    total_spend = sum(found_row["spend"][currency] for found_row in rows.values())
    out = [
        {
            "key": found_row["key"],
            "label": found_row["label"],
            "launched": found_row["launched"],
            "failed": found_row["failed"],
            "failed_pct": _pct(
                found_row["failed"], found_row["launched"] + found_row["failed"]
            ),
            "advertisers": len(found_row["advertisers"][currency]),
            "spend_minor": found_row["spend"][currency],
            "spend_share_pct": _pct(found_row["spend"][currency], total_spend),
            "lead_spend_minor": found_row["lead_spend"][currency],
            "leads": found_row["leads"][currency],
            "lead_cost_minor": formulas.cpl(
                found_row["lead_spend"][currency], found_row["leads"][currency]
            ),
        }
        for found_row in rows.values()
    ]
    out.sort(key=lambda found: (-found["spend_minor"], -found["launched"]))
    leads = sum(found["leads"] for found in out)
    lead_spend = sum(found["lead_spend_minor"] for found in out)
    launched = sum(found["launched"] for found in out)
    failed = sum(found["failed"] for found in out)
    return {
        "by": by,
        "currency": currency,
        "other_currency_campaigns": sum(
            1 for found in currency_of.values() if found != currency
        ),
        "rows": out,
        "total": {
            "launched": launched,
            "failed": failed,
            "failed_pct": _pct(failed, launched + failed),
            "spend_minor": total_spend,
            "lead_spend_minor": lead_spend,
            "leads": leads,
            "lead_cost_minor": formulas.cpl(lead_spend, leads),
        },
    }


# -- the assistant's cost ------------------------------------------------------------


def ai_cost(db: Session, *, window: Window, now: datetime) -> dict[str, Any]:
    """What Claude cost in the window, in USD micros (dollars = micros / 1e8).

    "Per customer a month" is the customers' cost over customer-months: a
    customer who used the assistant in two calendar months counts twice.
    """
    month = func.date_trunc(
        "month", func.timezone(settings.office_timezone, LLMCall.created_at)
    )
    in_window = and_(
        LLMCall.created_at >= window.since, LLMCall.created_at < window.until
    )
    rows = db.execute(
        select(
            month,
            LLMCall.owner_id,
            func.sum(exact_cost()),
            func.sum(LLMCall.input_tokens),
            func.sum(LLMCall.output_tokens),
            func.sum(LLMCall.cache_read_tokens),
            func.sum(LLMCall.cache_write_tokens),
            func.count(LLMCall.id),
        )
        .where(in_window, LLMCall.owner_id.in_(customer_ids()))
        .group_by(month, LLMCall.owner_id)
    ).all()
    staff = int(
        db.scalar(
            select(func.coalesce(func.sum(exact_cost()), 0)).where(
                in_window, LLMCall.owner_id.not_in(customer_ids())
            )
        )
        or 0
    )
    total = 0
    calls = 0
    tokens = Counter[str]()
    per_owner: Counter[uuid.UUID] = Counter()
    per_month: dict[datetime, list[int]] = defaultdict(list)
    for started, owner, cost, given, written, read, cached, count in rows:
        cost = int(cost or 0)
        total += cost
        calls += int(count or 0)
        tokens["input"] += int(given or 0)
        tokens["output"] += int(written or 0)
        tokens["cache_read"] += int(read or 0)
        tokens["cache_write"] += int(cached or 0)
        per_owner[owner] += cost
        per_month[started].append(cost)
    customer_months = sum(len(costs) for costs in per_month.values())

    def grouped(column: Any) -> list[tuple[str, int, int, int]]:
        return [
            (str(key or ""), int(cost or 0), int(users or 0), int(count or 0))
            for key, cost, users, count in db.execute(
                select(
                    column,
                    func.sum(exact_cost()),
                    func.count(distinct(LLMCall.owner_id)),
                    func.count(LLMCall.id),
                )
                .where(in_window, LLMCall.owner_id.in_(customer_ids()))
                .group_by(column)
                .order_by(func.sum(exact_cost()).desc())
            )
        ]

    plans = _plan_of(db, now=now)
    top = per_owner.most_common(TOP)
    emails: dict[uuid.UUID, str] = {
        person: email
        for person, email in db.execute(
            select(User.id, User.email).where(User.id.in_([o for o, _ in top]))
        )
    }
    by_plan: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    plan_months: Counter[str] = Counter()
    for costs_owner, cost in per_owner.items():
        name = plans.get(costs_owner, "Obunasiz")
        by_plan[name][0] += cost
        by_plan[name][1] += 1
    for _month, owner, *_rest in rows:
        plan_months[plans.get(owner, "Obunasiz")] += 1
    return {
        "currency": settings.anthropic_price_currency,
        "micros_per_unit": USD_MICROS,
        "cost_micros": total,
        "staff_cost_micros": staff,
        "calls": calls,
        "tokens": dict(tokens),
        "customers": len(per_owner),
        "customer_months": customer_months,
        "per_customer_month_micros": monthly_rate(
            cost=total,
            customer_months=customer_months,
            customers=len(per_owner),
            days=window.days,
        ),
        "months": [
            {
                "month": f"{started:%Y-%m}",
                "label": f"{MONTH_LABELS[started.month - 1]} {started.year}",
                "customers": len(costs),
                "cost_micros": sum(costs),
                "average_micros": sum(costs) // len(costs),
                "median_micros": int(statistics.median(costs)),
            }
            for started, costs in sorted(per_month.items())
        ],
        "purposes": [
            {
                "key": key,
                "label": str(LLM_PURPOSE_LABELS.get(key, key)) if key else NO_VALUE,
                "cost_micros": cost,
                "share_pct": _pct(cost, total),
                "customers": users,
                "calls": count,
            }
            for key, cost, users, count in grouped(LLMCall.purpose)
        ],
        "models": [
            {
                "key": key,
                "label": key or NO_VALUE,
                "cost_micros": cost,
                "share_pct": _pct(cost, total),
                "customers": users,
                "calls": count,
            }
            for key, cost, users, count in grouped(LLMCall.model)
        ],
        "plans": [
            {
                "name": name,
                "customers": users,
                "cost_micros": cost,
                "per_customer_month_micros": (
                    cost // plan_months[name] if plan_months[name] else 0
                ),
            }
            for name, (cost, users) in sorted(by_plan.items(), key=lambda i: -i[1][0])
        ],
        "top": [
            {"id": str(owner), "email": emails.get(owner, ""), "cost_micros": cost}
            for owner, cost in top
        ],
    }


def _plan_of(db: Session, *, now: datetime) -> dict[uuid.UUID, str]:
    """Every owner's plan now: the plan's name while paid up, "Sinov" in a
    trial; absent when nothing is live. One query over the live ones."""
    found: dict[uuid.UUID, str] = {}
    for owner, name, status in db.execute(
        select(Subscription.owner_id, Plan.name, Subscription.status)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            Subscription.expires_at > now,
        )
        .order_by(Subscription.expires_at)
    ):
        found[owner] = "Sinov" if status == SubscriptionStatus.TRIAL else name
    return found


# -- who the customers are --------------------------------------------------------


def paying_now(now: datetime) -> Select[tuple[uuid.UUID]]:
    return select(Subscription.owner_id).where(
        Subscription.status == SubscriptionStatus.ACTIVE,
        Subscription.expires_at > now,
        not_demo(Subscription.owner_id),
    )


def ever_paid() -> Select[tuple[uuid.UUID]]:
    return select(Invoice.owner_id).where(
        Invoice.archived_at.is_(None),
        Invoice.status == InvoiceStatus.PAID,
        Invoice.kind == InvoiceKind.PLAN,
        Invoice.owner_id.is_not(None),
        or_(Invoice.amount_minor != 0, Invoice.wallet_minor != 0),
        not_demo(Invoice.owner_id),
    )


def businesses(db: Session, *, window: Window, now: datetime) -> dict[str, Any]:
    """Businesses by direction, now; one customer may own several, so both
    the businesses and their distinct owners are counted."""
    paying = paying_now(now)
    kind = case(
        (Business.direction_id.is_not(None), BusinessCategory.key),
        (Business.custom_category_id.is_not(None), "custom"),
        else_="none",
    )
    rows = db.execute(
        select(
            kind,
            func.max(BusinessCategory.label_uz),
            func.count(Business.id),
            func.count(distinct(Business.user_id)),
            func.count(
                distinct(case((Business.user_id.in_(paying), Business.user_id)))
            ),
            func.count(
                case(
                    (
                        and_(
                            Business.created_at >= window.since,
                            Business.created_at < window.until,
                        ),
                        Business.id,
                    )
                )
            ),
        )
        .join(User, User.id == Business.user_id)
        .outerjoin(BusinessCategory, BusinessCategory.id == Business.direction_id)
        .where(_customer())
        .group_by(kind)
    ).all()
    total = sum(int(row[2]) for row in rows)
    named = {"custom": "O'zi yozgan", "none": "Tanlanmagan"}
    out = [
        {
            "key": key,
            "label": named.get(key) or label or key,
            "businesses": int(count),
            "share_pct": _pct(int(count), total),
            "owners": int(owners),
            "paying_owners": int(paying_owners),
            "paying_pct": _pct(int(paying_owners), int(owners)),
            "new_in_window": int(fresh),
        }
        for key, label, count, owners, paying_owners, fresh in rows
    ]
    out.sort(key=lambda row: (row["key"] in named, -row["businesses"]))
    custom = db.execute(
        select(CustomCategory.label, func.count(Business.id))
        .join(Business, Business.custom_category_id == CustomCategory.id)
        .join(User, User.id == Business.user_id)
        .where(_customer(), Business.direction_id.is_(None))
        .group_by(CustomCategory.label)
        .order_by(func.count(Business.id).desc())
        .limit(TOP)
    ).all()
    city = func.initcap(func.trim(Business.city))
    cities = db.execute(
        select(city, func.count(Business.id))
        .join(User, User.id == Business.user_id)
        .where(_customer(), func.trim(Business.city) != "")
        .group_by(city)
        .order_by(func.count(Business.id).desc())
        .limit(TOP)
    ).all()
    no_city = int(
        db.scalar(
            select(func.count(Business.id))
            .join(User, User.id == Business.user_id)
            .where(_customer(), func.trim(Business.city) == "")
        )
        or 0
    )
    return {
        "total": total,
        "owners": int(
            db.scalar(
                select(func.count(distinct(Business.user_id)))
                .join(User, User.id == Business.user_id)
                .where(_customer())
            )
            or 0
        ),
        "directions": out,
        "custom_top": [
            {
                "label": label,
                "businesses": int(count),
                "share_pct": _pct(int(count), total),
            }
            for label, count in custom
        ],
        "cities": [
            {
                "label": label,
                "businesses": int(count),
                "share_pct": _pct(int(count), total),
            }
            for label, count in cities
        ],
        "no_city": no_city,
    }


def people(db: Session, *, window: Window, now: datetime) -> dict[str, Any]:
    """Customers by role, by how they signed up, by language and by the ad
    that brought them: how many, how many came in the window, how many have
    ever paid and how many pay now. One grouped query per dimension."""
    paid = ever_paid()
    paying = paying_now(now)
    fresh = and_(User.date_joined >= window.since, User.date_joined < window.until)

    def split(
        column: Any, labels: dict[str, str], limit: int | None = None
    ) -> dict[str, Any]:
        query = (
            select(
                column,
                func.count(User.id),
                func.count(case((fresh, User.id))),
                func.count(case((User.id.in_(paid), User.id))),
                func.count(case((User.id.in_(paying), User.id))),
            )
            .where(_customer())
            .group_by(column)
            .order_by(func.count(User.id).desc())
        )
        rows = db.execute(query).all()
        total = sum(int(row[1]) for row in rows)
        out = [
            {
                "key": str(key or ""),
                "label": labels.get(str(key or ""), str(key)) if key else NO_VALUE,
                "customers": int(count),
                "share_pct": _pct(int(count), total),
                "joined_in_window": int(joined),
                "ever_paid": int(ever),
                "paid_pct": _pct(int(ever), int(count)),
                "paying_now": int(now_paying),
            }
            for key, count, joined, ever, now_paying in rows
        ]
        if limit is not None and len(out) > limit:
            head, tail = out[:limit], out[limit:]
            rest = {
                "key": "_rest",
                "label": "Boshqalar",
                "customers": sum(row["customers"] for row in tail),
                "joined_in_window": sum(row["joined_in_window"] for row in tail),
                "ever_paid": sum(row["ever_paid"] for row in tail),
                "paying_now": sum(row["paying_now"] for row in tail),
            }
            rest["share_pct"] = _pct(rest["customers"], total)
            rest["paid_pct"] = _pct(rest["ever_paid"], rest["customers"])
            out = [*head, rest]
        return {"total": total, "rows": out}

    source = func.nullif(func.lower(func.trim(User.signup_utm["source"].astext)), "")
    return {
        "roles": split(User.role, {str(k): str(v) for k, v in ROLE_LABELS.items()}),
        "signup_via": split(
            User.signup_via, {str(k): str(v) for k, v in SIGNUP_VIA_LABELS.items()}
        ),
        "languages": split(
            User.language, {"uz": "O'zbekcha", "ru": "Ruscha", "en": "Inglizcha"}
        ),
        "utm_sources": split(source, {}, limit=TOP),
    }


# -- money ---------------------------------------------------------------------------


def money(
    db: Session, buyers: dict[str, Buyer], *, window: Window, now: datetime
) -> dict[str, Any]:
    """Takings inside the window by what was sold and how it was paid, the
    average per paying customer, the lifetime value, and autopay's reach."""
    method = (
        select(
            PaymentTransaction.invoice_id,
            func.max(PaymentTransaction.provider).label("provider"),
        )
        .where(PaymentTransaction.state == TransactionState.PERFORMED)
        .group_by(PaymentTransaction.invoice_id)
        .subquery()
    )
    rows = db.execute(
        select(
            Invoice.kind,
            Invoice.currency,
            Invoice.manual_method,
            method.c.provider,
            Invoice.amount_minor,
            Invoice.wallet_minor,
            Invoice.offer_minor,
            Invoice.owner_id,
            Invoice.former_email,
            Invoice.pages_minor,
            Invoice.seats_minor,
        )
        .outerjoin(User, User.id == Invoice.owner_id)
        .outerjoin(method, method.c.invoice_id == Invoice.id)
        .where(
            Invoice.archived_at.is_(None),
            Invoice.status == InvoiceStatus.PAID,
            Invoice.paid_at >= window.since,
            Invoice.paid_at < window.until,
            or_(Invoice.amount_minor != 0, Invoice.wallet_minor != 0),
            or_(Invoice.owner_id.is_(None), _customer()),
        )
    ).all()
    currency = main_currency([row.currency for row in rows])
    mine = [row for row in rows if row.currency == currency]
    kinds: Counter[str] = Counter()
    kind_bills: Counter[str] = Counter()
    methods: Counter[str] = Counter()
    method_bills: Counter[str] = Counter()
    wallet = offers = 0
    plan_payers: set[str] = set()
    for row in mine:
        if row.kind == InvoiceKind.PLAN:
            plan = plan_part(row.amount_minor, row.pages_minor, row.seats_minor)
            riding = row.amount_minor - plan
            pages = min(row.pages_minor, riding)
            kinds[InvoiceKind.PLAN] += plan
            kinds[InvoiceKind.PAGES] += pages
            kinds[InvoiceKind.SEATS] += riding - pages
        else:
            kinds[row.kind] += row.amount_minor
        kind_bills[row.kind] += 1
        how = (
            f"manual:{row.manual_method}"
            if row.manual_method
            else row.provider or ("wallet" if row.amount_minor == 0 else "other")
        )
        methods[how] += row.amount_minor
        method_bills[how] += 1
        wallet += row.wallet_minor
        offers += row.offer_minor
        key = payer_key(row.owner_id, row.former_email)
        if row.kind == InvoiceKind.PLAN and key:
            plan_payers.add(key)
    takings = sum(kinds.values())
    refunded = db.execute(
        select(func.count(Invoice.id), func.coalesce(func.sum(Invoice.amount_minor), 0))
        .outerjoin(User, User.id == Invoice.owner_id)
        .where(
            Invoice.status == InvoiceStatus.REFUNDED,
            Invoice.currency == currency,
            Invoice.paid_at >= window.since,
            Invoice.paid_at < window.until,
            or_(Invoice.owner_id.is_(None), _customer()),
        )
    ).one()
    lifetime = [
        bill.amount_minor
        for buyer in buyers.values()
        for bill in buyer.upto(window.until)
        if bill.currency == currency
    ]
    lifetime_buyers = sum(
        1
        for buyer in buyers.values()
        if any(bill.currency == currency for bill in buyer.upto(window.until))
    )
    live_paying = paying_now(now).where(Subscription.owner_id.in_(customer_ids()))
    paying, with_card = db.execute(
        select(
            func.count(distinct(User.id)),
            func.count(
                distinct(
                    case(
                        (
                            User.id.in_(
                                select(SavedCard.owner_id).where(
                                    SavedCard.status == CardStatus.ACTIVE
                                )
                            ),
                            User.id,
                        )
                    )
                )
            ),
        ).where(User.id.in_(live_paying))
    ).one()
    plan_takings = kinds[InvoiceKind.PLAN]
    return {
        "currency": currency,
        "takings_minor": takings,
        "bills": len(mine),
        "kinds": [
            {
                "key": key,
                "label": label,
                "amount_minor": kinds[key],
                "share_pct": _pct(kinds[key], takings),
                "bills": kind_bills[key],
            }
            for key, label in (
                (InvoiceKind.PLAN, "Tarif"),
                (InvoiceKind.PAGES, "Qo'shimcha sahifa"),
                (InvoiceKind.SEATS, "CRM menejeri"),
            )
        ],
        "methods": [
            {
                "key": key,
                "label": _method_label(key),
                "amount_minor": amount,
                "bills": method_bills[key],
                "share_pct": _pct(amount, takings),
            }
            for key, amount in methods.most_common()
        ],
        "plan_payers": len(plan_payers),
        "per_payer_minor": plan_takings // len(plan_payers) if plan_payers else 0,
        "lifetime_per_customer_minor": (
            sum(lifetime) // lifetime_buyers if lifetime_buyers else 0
        ),
        "wallet_minor": wallet,
        "discount_minor": offers,
        "refunded": int(refunded[0] or 0),
        "refunded_minor": int(refunded[1] or 0),
        "paying_now": int(paying or 0),
        "autopay_now": int(with_card or 0),
        "autopay_pct": _pct(int(with_card or 0), int(paying or 0)),
    }


def _method_label(key: str) -> str:
    manual = {
        "cash": "Naqd (qo'lda)",
        "transfer": "O'tkazma (qo'lda)",
        "card": "Karta (qo'lda)",
    }
    if key.startswith("manual:"):
        return manual.get(key.removeprefix("manual:"), "Qo'lda")
    return {
        "payme": "Payme",
        "click": "Click",
        "multicard": "Karta (Rahmat)",
        "wallet": "Hamyon",
        "other": "Boshqa",
    }.get(key, key)


# -- what paying customers use -------------------------------------------------------


def usage(db: Session, *, window: Window, now: datetime) -> dict[str, Any]:
    """Of the customers paying now, how many use each part of the product;
    and what the platform did inside the window."""
    paying = paying_now(now).where(Subscription.owner_id.in_(customer_ids()))
    total = int(
        db.scalar(select(func.count(distinct(User.id))).where(User.id.in_(paying))) or 0
    )
    parts: tuple[tuple[str, str, Any], ...] = (
        ("launch", "Reklama chiqargan (30 kun)", select(CampaignLaunch.owner_id).where(
            CampaignLaunch.status == LaunchStatus.CREATED,
            CampaignLaunch.created_at >= now - timedelta(days=30),
        )),
        ("leads", "Lid olgan (30 kun)", select(Lead.owner_id).where(
            Lead.created_at >= now - timedelta(days=30),
            Lead.provider != MANUAL_PROVIDER,
        )),
        ("crm", "CRM ochgan", select(CrmSetup.owner_id)),
        ("templates", "Chat shabloni", select(ChatTemplate.owner_id)),
        ("sheets", "Google Sheets", select(FormSheet.owner_id)),
        ("lead_chats", "Lidlar Telegram'ga", select(LeadChat.owner_id)),
        ("montage", "Video montaj", select(Montage.owner_id)),
        ("telephony", "Telefoniya", select(PhoneConnection.owner_id).where(
            PhoneConnection.owner_id.is_not(None)
        )),
        ("google", "Google Ads", select(GoogleLaunch.owner_id)),
        ("autopay", "Avtoto'lov kartasi", select(SavedCard.owner_id).where(
            SavedCard.status == CardStatus.ACTIVE
        )),
    )  # fmt: skip
    counts = db.execute(
        select(
            *[
                func.count(distinct(case((User.id.in_(query), User.id))))
                for _, _, query in parts
            ]
        ).where(User.id.in_(paying))
    ).one()
    launches = db.execute(
        select(
            func.count(case((CampaignLaunch.status == LaunchStatus.CREATED, 1))),
            func.count(case((CampaignLaunch.status == LaunchStatus.FAILED, 1))),
            func.count(
                distinct(
                    case(
                        (
                            CampaignLaunch.status == LaunchStatus.CREATED,
                            CampaignLaunch.owner_id,
                        )
                    )
                )
            ),
        ).where(
            CampaignLaunch.owner_id.in_(customer_ids()),
            CampaignLaunch.created_at >= window.since,
            CampaignLaunch.created_at < window.until,
        )
    ).one()
    leads = db.execute(
        select(func.count(Lead.id), func.count(distinct(Lead.owner_id))).where(
            Lead.owner_id.in_(customer_ids()),
            Lead.provider != MANUAL_PROVIDER,
            Lead.created_at >= window.since,
            Lead.created_at < window.until,
        )
    ).one()
    created, failed, launchers = (int(value or 0) for value in launches)
    return {
        "paying_now": total,
        "parts": [
            {
                "key": key,
                "label": label,
                "customers": int(count or 0),
                "share_pct": _pct(int(count or 0), total),
            }
            for (key, label, _), count in zip(parts, counts, strict=True)
        ],
        "launched": created,
        "failed": failed,
        "failed_pct": _pct(failed, created + failed),
        "launchers": launchers,
        "leads": int(leads[0] or 0),
        "lead_owners": int(leads[1] or 0),
        "leads_per_owner": (
            round(int(leads[0]) / int(leads[1]), 1) if leads[1] else None
        ),
    }


def live_owner_ids(db: Session, *, now: datetime) -> set[uuid.UUID]:
    return set(db.scalars(paying_now(now)))


def every_plan(db: Session) -> list[Plan]:
    return list(db.scalars(select(Plan).order_by(Plan.sort_order, Plan.price)))


def lost_people(
    db: Session, owners: list[uuid.UUID | None], *, limit: int
) -> list[User]:
    ids = [owner for owner in owners if owner is not None]
    if not ids:
        return []
    return list(
        db.scalars(
            select(User)
            .where(User.id.in_(ids))
            .order_by(User.date_joined.desc())
            .limit(limit)
        )
    )


# -- the headline, over time, now, and what brings customers in ---------------------


def _change(now: int, before: int) -> float | None:
    """Percent moved against the window before; none from nothing."""
    return round((now - before) * 100 / before, 1) if before else None


def _signup_days(db: Session, *, window: Window) -> list[datetime]:
    return list(
        db.scalars(
            select(User.date_joined).where(
                _customer(),
                User.date_joined >= window.since,
                User.date_joined < window.until,
            )
        )
    )


def _moments(
    buyers: dict[str, Buyer], *, window: Window, currency: str
) -> dict[str, list[tuple[datetime, int]]]:
    """What happened inside the window, each with when: first buyers, who
    reached yellow and green, and plan takings in one currency."""
    out: dict[str, list[tuple[datetime, int]]] = defaultdict(list)

    def inside(moment: datetime | None) -> bool:
        return moment is not None and window.since <= moment < window.until

    for buyer in buyers.values():
        if not buyer.bills:
            continue
        if inside(buyer.bills[0].paid_at):
            out["first_buyers"].append((buyer.bills[0].paid_at, 1))
        step = climb(buyer.bills)
        onward = (
            min(m for m in (step.yellow, step.green) if m)
            if step.yellow or step.green
            else None
        )
        if inside(onward):
            out["reached_yellow"].append((onward, 1))
        if step.green and inside(step.green):
            out["reached_green"].append((step.green, 1))
        for bill in buyer.bills:
            if inside(bill.paid_at) and bill.currency == currency:
                out["plan_takings_minor"].append((bill.paid_at, bill.amount_minor))
    return out


# Shorter than this, a window holds no whole month: its cost is brought to 30 days.
WHOLE_MONTH_DAYS = 28


def monthly_rate(*, cost: int, customer_months: int, customers: int, days: int) -> int:
    """A customer's AI cost a month: over customer-months for a month or more;
    for a day or a week, the cost per customer brought to 30 days, so the
    figure means the same on every window."""
    if days >= WHOLE_MONTH_DAYS:
        return cost // customer_months if customer_months else 0
    return cost * 30 // (customers * days) if customers and days else 0


def _ai_rate(db: Session, *, window: Window) -> tuple[int, int, int]:
    """Customers' AI cost, customer-months and customers inside a window."""
    month = func.date_trunc(
        "month", func.timezone(settings.office_timezone, LLMCall.created_at)
    )
    per = (
        select(LLMCall.owner_id.label("owner"), func.sum(exact_cost()).label("cost"))
        .where(
            LLMCall.owner_id.in_(customer_ids()),
            LLMCall.created_at >= window.since,
            LLMCall.created_at < window.until,
        )
        .group_by(month, LLMCall.owner_id)
        .subquery()
    )
    cost, months, people = db.execute(
        select(
            func.coalesce(func.sum(per.c.cost), 0),
            func.count(),
            func.count(distinct(per.c.owner)),
        )
    ).one()
    return int(cost or 0), int(months or 0), int(people or 0)


KPI_LABELS = (
    ("plan_takings_minor", "Tarif tushumi"),
    ("signups", "Ro'yxatdan o'tganlar"),
    ("first_buyers", "Yangi xaridorlar"),
    ("reached_yellow", "Standart yoki yuqoriga o'tganlar"),
    ("reached_green", "Standart 2+ marta yoki Pro olganlar"),
    ("ai_per_customer_month_micros", "AI / mijoz / oy"),
)


def headline(
    db: Session,
    buyers: dict[str, Buyer],
    *,
    window: Window,
    currency: str,
    ai_now: int,
) -> list[dict[str, Any]]:
    """The top row: each figure for this window and the same number of days
    just before it."""

    def figures(frame: Window, ai: int | None = None) -> dict[str, int]:
        found = {
            key: sum(n for _, n in rows)
            for key, rows in _moments(buyers, window=frame, currency=currency).items()
        }
        found["signups"] = len(_signup_days(db, window=frame))
        if ai is None:
            cost, months, people = _ai_rate(db, window=frame)
            ai = monthly_rate(
                cost=cost, customer_months=months, customers=people, days=frame.days
            )
        found["ai_per_customer_month_micros"] = ai
        return found

    now, before = figures(window, ai_now), figures(window.before())
    return [
        {
            "key": key,
            "label": label,
            "value": now.get(key, 0),
            "before": before.get(key, 0),
            "change_pct": _change(now.get(key, 0), before.get(key, 0)),
        }
        for key, label in KPI_LABELS
    ]


def series(
    db: Session, buyers: dict[str, Buyer], *, window: Window, currency: str
) -> dict[str, Any]:
    """The same figures bar by bar across the window (a day, a week or a
    month each, as the dashboard draws them)."""
    per_bar: dict[str, Counter[Any]] = {
        key: Counter()
        for key in (
            "signups",
            "first_buyers",
            "reached_yellow",
            "reached_green",
            "plan_takings_minor",
        )
    }
    for key, rows in _moments(buyers, window=window, currency=currency).items():
        for moment, amount in rows:
            per_bar[key][window.bar_of(localtime(moment).date())] += amount
    for joined in _signup_days(db, window=window):
        per_bar["signups"][window.bar_of(localtime(joined).date())] += 1
    return {
        "unit": window.unit,
        "currency": currency,
        "bars": [
            {
                "key": start.isoformat(),
                "label": bar_label(start, window.unit),
                "hint": bar_hint(start, window),
                **{key: counts[start] for key, counts in per_bar.items()},
            }
            for start in window.bars()
        ],
    }


def statuses(db: Session, *, now: datetime) -> dict[str, Any]:
    """Every customer now by their plan's state, and the paid ones whose time
    runs out soon, with how many of those have a card to renew from."""
    paid = paying_now(now)
    trial = select(Subscription.owner_id).where(
        Subscription.status == SubscriptionStatus.TRIAL,
        Subscription.expires_at > now,
    )
    had = select(Subscription.owner_id)
    total, paying, trying, ended = (
        int(value or 0)
        for value in db.execute(
            select(
                func.count(User.id),
                func.count(case((User.id.in_(paid), User.id))),
                func.count(
                    case((and_(User.id.in_(trial), User.id.not_in(paid)), User.id))
                ),
                func.count(
                    case(
                        (
                            and_(
                                User.id.in_(had),
                                User.id.not_in(paid),
                                User.id.not_in(trial),
                            ),
                            User.id,
                        )
                    )
                ),
            ).where(_customer())
        ).one()
    )
    never = total - paying - trying - ended
    carded = select(SavedCard.owner_id).where(SavedCard.status == CardStatus.ACTIVE)

    def soon(days: int) -> Any:
        return and_(
            Subscription.expires_at < now + timedelta(days=days),
            Subscription.owner_id.in_(carded),
        )

    ends = db.execute(
        select(
            *[
                func.count(
                    distinct(
                        case(
                            (
                                Subscription.expires_at < now + timedelta(days=days),
                                Subscription.owner_id,
                            )
                        )
                    )
                )
                for days in (7, 30)
            ],
            *[
                func.count(distinct(case((soon(days), Subscription.owner_id))))
                for days in (7, 30)
            ],
        ).where(
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.expires_at > now,
            Subscription.owner_id.in_(customer_ids()),
        )
    ).one()
    rows = (
        ("paying", "Obunasi faol", paying),
        ("trial", "Sinovda", trying),
        ("ended", "Muddati tugagan", ended),
        ("never", "Hech qachon obuna bo'lmagan", never),
    )
    return {
        "total": total,
        "rows": [
            {
                "key": key,
                "label": label,
                "customers": count,
                "share_pct": _pct(count, total),
            }
            for key, label, count in rows
        ],
        "ending_7": int(ends[0] or 0),
        "ending_30": int(ends[1] or 0),
        "ending_7_with_card": int(ends[2] or 0),
        "ending_30_with_card": int(ends[3] or 0),
    }


def growth(db: Session, *, window: Window, currency: str) -> dict[str, Any]:
    """Promo codes and referrals inside the window."""
    inside_promo = and_(
        PromoRedemption.redeemed_at >= window.since,
        PromoRedemption.redeemed_at < window.until,
        PromoRedemption.status == RedemptionStatus.APPROVED,
        PromoRedemption.owner_id.in_(customer_ids()),
    )
    promo = db.execute(
        select(
            func.count(PromoRedemption.id),
            func.count(distinct(PromoRedemption.owner_id)),
            func.coalesce(func.sum(PromoRedemption.discount_minor), 0),
            func.coalesce(func.sum(PromoRedemption.granted_days), 0),
        ).where(inside_promo)
    ).one()
    referred = db.execute(
        select(
            func.count(distinct(ReferralBinding.owner_id)),
            func.count(
                distinct(
                    case(
                        (
                            ReferralBinding.owner_id.in_(ever_paid()),
                            ReferralBinding.owner_id,
                        )
                    )
                )
            ),
            func.count(distinct(ReferralBinding.referrer_id)),
        ).where(
            ReferralBinding.referrer_id.is_not(None),
            ReferralBinding.created_at >= window.since,
            ReferralBinding.created_at < window.until,
            ReferralBinding.owner_id.in_(customer_ids()),
            ReferralBinding.referrer_id.in_(customer_ids()),
        )
    ).one()
    rewards = db.execute(
        select(
            func.count(ReferralReward.id),
            func.coalesce(func.sum(ReferralReward.amount_minor), 0),
        ).where(
            ReferralReward.earned_at >= window.since,
            ReferralReward.earned_at < window.until,
            ReferralReward.currency == currency,
            ReferralReward.owner_id.in_(customer_ids()),
        )
    ).one()
    came, paid, referrers = (int(value or 0) for value in referred)
    return {
        "currency": currency,
        "promo_used": int(promo[0] or 0),
        "promo_customers": int(promo[1] or 0),
        "promo_discount_minor": int(promo[2] or 0),
        "promo_days": int(promo[3] or 0),
        "referred": came,
        "referred_paid": paid,
        "referred_paid_pct": _pct(paid, came),
        "referrers": referrers,
        "rewards": int(rewards[0] or 0),
        "rewards_minor": int(rewards[1] or 0),
    }
