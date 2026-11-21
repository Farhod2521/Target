"""The office's figures as the assistant reads them: plain lines of text.

Every look-up is a selector the office already has - the dashboard's, the
customers list's, the plans' - read here and written out. Figures a person
usually wants worked out (a change against the window before, a share, a
conversion) are worked out here: the answer may quote only what a look-up
gave, so nothing has to be computed by the model.
"""

from collections import Counter
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.backoffice.constants import EXPIRING_DAYS
from app.modules.backoffice.selectors.customers import Narrowing, customer_page
from app.modules.backoffice.selectors.dashboard import (
    Window,
    activity,
    asked_window,
    bar_hint,
    customers,
    recent_payments,
    sales,
    takings,
    waiting,
)
from app.modules.backoffice.selectors.problems import problems
from app.modules.billing.constants import (
    LIVE_SUBSCRIPTION_STATUSES,
    SubscriptionStatus,
)
from app.modules.billing.models import Plan, Subscription
from app.modules.integrations.selectors.demo import not_demo
from app.modules.officeai.constants import LIST_ROWS, PROBLEM_ROWS
from core.officeai.tools import CustomerQuery, Span


def window_of(span: Span, *, today: date) -> Window:
    return asked_window(
        period=span.period, since=span.since, until=span.until, today=today
    )


def _money(amount: int, currency: str) -> str:
    return format_minor(amount_minor=amount, currency=currency)


def _money_diff(now: int, before: int, currency: str) -> str:
    if now == before:
        return "the same"
    return f"{_money(abs(now - before), currency)} {'more' if now > before else 'less'}"


def _pct(value: int | None) -> str:
    if value is None:
        return "n/a (nothing to compare with)"
    return f"{value:+d}%"


def _diff(now: int, before: int) -> str:
    """How far apart two counts are, so nobody has to subtract."""
    if now == before:
        return "the same"
    return f"{abs(now - before)} {'more' if now > before else 'fewer'}"


def _day(moment: datetime | date | None) -> str:
    if moment is None:
        return "-"
    if isinstance(moment, datetime):
        return f"{localtime(moment):%d.%m.%Y %H:%M}"
    return f"{moment:%d.%m.%Y}"


def _heading(title: str, window: Window) -> list[str]:
    lines = [
        f"## {title}",
        f"Window: {window.start:%d.%m.%Y} - {window.end:%d.%m.%Y} "
        f"({window.days} days, office time).",
    ]
    if window.refused:
        lines.append(f"The days asked for were not read: {window.refused}")
    return lines


# -- customers -----------------------------------------------------------------


def _signups_by_bar(db: Session, window: Window) -> Counter[date]:
    joined = db.scalars(
        select(User.date_joined).where(
            User.is_staff.is_(False),
            User.crm_owner_id.is_(None),
            User.date_joined >= window.since,
            User.date_joined < window.until,
        )
    )
    return Counter(window.bar_of(localtime(moment).date()) for moment in joined)


def customers_summary(db: Session, *, span: Span, now: datetime) -> str:
    window = window_of(span, today=localtime(now).date())
    found = customers(db, window=window, now=now)
    per_bar = _signups_by_bar(db, window)
    lines = [
        *_heading("Customers", window),
        f"- Customers in all (staff never counted): {found.total}",
        f"- Signed up in the window: {found.joined}",
        f"- Signed up in the {window.days} days before it: {found.joined_before}"
        f" ({_diff(found.joined, found.joined_before)} now;"
        f" change: {_pct(found.joined_change_pct)})",
        f"- Of those who signed up in the window, paid for a plan: "
        f"{found.joined_paid} (conversion: "
        f"{f'{found.conversion_pct}%' if found.conversion_pct is not None else 'n/a'})"
        f"; did not pay: {found.joined - found.joined_paid}",
        f"- On a trial now: {found.trial}",
        f"- On a paid plan now: {found.paying}",
        f"- Plan ends within {EXPIRING_DAYS} days: {found.expiring}",
        f"- Plan ended in the window and not renewed: {found.churned}",
        f"- Plan live, setup not finished: {found.setup_unfinished}",
        f"- Plan live, Facebook not connected: {found.meta_missing}",
        "",
        f"### Sign-ups per {window.unit}",
    ]
    lines += [
        f"- {bar_hint(start, window)}: {per_bar.get(start, 0)}"
        for start in window.bars()
    ]
    return "\n".join(lines)


# -- money ---------------------------------------------------------------------


def money_summary(db: Session, *, span: Span, now: datetime) -> str:
    today = localtime(now).date()
    window = window_of(span, today=today)
    found = takings(db, window=window, today=today)
    whole, currency = found.whole, found.currency
    lines = [
        *_heading("Takings", window),
        f"Currency: {currency} (bills in another currency are not summed in).",
        f"- Money in: {_money(whole.amount_minor, currency)}",
        f"- Payments: {whole.payments}",
        f"- Average payment: {_money(whole.average_minor, currency)}",
        f"- Paid online: {_money(whole.online_minor, currency)}; "
        f"entered by hand: {_money(whole.manual_minor, currency)}",
        f"- Money in, the {window.days} days before: "
        f"{_money(found.before_minor, currency)} ("
        f"{_money_diff(whole.amount_minor, found.before_minor, currency)} now; "
        f"change: {_pct(found.change_pct)})",
        f"- Unpaid bills now: {found.unpaid}, {_money(found.unpaid_minor, currency)}",
        f"- Plans given free in the window: {found.given_free}",
        "",
        "### Per plan",
    ]
    lines += [
        f"- {plan.name}: {plan.payments} payments, "
        f"{_money(plan.amount_minor, currency)} ({plan.share_pct}%)"
        for plan in whole.plans
    ] or ["- no payments"]
    lines += ["", f"### Per {window.unit}"]
    lines += [
        f"- {bar.hint}: {_money(bar.figures.amount_minor, currency)}, "
        f"{bar.figures.payments} payments, {bar.figures.signups} sign-ups"
        for bar in found.bars
    ]
    return "\n".join(lines)


def latest_payments(db: Session) -> str:
    rows = recent_payments(db)
    if not rows:
        return "## Last payments\nNone yet."
    return "\n".join(
        [
            "## Last payments (newest first)",
            *(
                f"- {_day(row.paid_at)} - {row.email or 'deleted account'} - "
                f"{row.plan} - {_money(row.amount_minor, row.currency)}"
                f"{' (entered by hand)' if row.manual else ''}"
                for row in rows
            ),
        ]
    )


# -- the platform --------------------------------------------------------------


def platform_activity(
    db: Session, *, span: Span, now: datetime, sees_money: bool
) -> str:
    window = window_of(span, today=localtime(now).date())
    found = activity(db, window=window)
    spend = (
        ", ".join(_money(amount, currency) for currency, amount in found.spend)
        or "nothing"
    )
    lines = [
        *_heading("What the product did", window),
        "Only campaigns this product launched count; staff accounts never do.",
        f"- Campaigns running now: {found.running}",
        f"- Campaigns launched in the window: {found.launched}",
        f"- Launches that failed in the window: {found.failed}",
        f"- Ad spend in the window: {spend}",
        f"- Leads in the window: {found.leads}; the {window.days} days before: "
        f"{found.leads_before} ({_diff(found.leads, found.leads_before)} now; "
        f"change: {_pct(found.leads_change_pct)})",
    ]
    if sees_money:
        lines.append(
            f"- What the AI cost in the window: "
            f"{_money(found.ai_cost_minor, found.ai_currency)}"
        )
    return "\n".join(lines)


# -- what waits ----------------------------------------------------------------


def waiting_now(db: Session, *, now: datetime) -> str:
    queues = waiting(db, now=now)
    found = problems(db, now=now)
    urgent = sum(1 for problem in found if problem.urgent)
    lines = [
        "## Waiting on a person now",
        f"- Support chats with no answer: {queues.support}"
        + (
            f" (oldest since {_day(queues.support_oldest)})"
            if queues.support_oldest
            else ""
        ),
        f"- Promo code requests: {queues.promos}",
        f"- Plan requests: {queues.asks}",
        f"- Feedback to answer: {queues.feedback}",
        f"- Sales requests (arizalar): {queues.arizas}",
        f"- Payments stuck on hold: {queues.holds}",
        f"- Block suggestions to decide: {queues.block_suggestions}",
        "",
        f"## Problem list: {len(found)} in all, {urgent} urgent",
    ]
    lines += [
        f"- {'[urgent] ' if problem.urgent else ''}{problem.label} - "
        f"{problem.who}: {problem.what}"
        + (f" (since {_day(problem.since)})" if problem.since else "")
        for problem in found[:PROBLEM_ROWS]
    ]
    if len(found) > PROBLEM_ROWS:
        lines.append(f"- … and {len(found) - PROBLEM_ROWS} more on the dashboard.")
    return "\n".join(lines)


# -- sales ---------------------------------------------------------------------


def sales_by_manager(db: Session, *, span: Span, now: datetime) -> str:
    window = window_of(span, today=localtime(now).date())
    rows = sales(db, window=window)
    lines = _heading("Sales per manager", window)
    if not rows:
        return "\n".join([*lines, "No manager sold or holds a card."])
    lines += [
        f"- {row.manager.full_name or row.manager.email}: sold {row.sold}, "
        f"cards open now {row.open}"
        for row in rows
    ]
    lines.append(
        f"- In all: sold {sum(row.sold for row in rows)}, "
        f"open {sum(row.open for row in rows)}"
    )
    return "\n".join(lines)


# -- customers, one by one -----------------------------------------------------

# The order the customers list gives each state, in words.
_ORDER = {
    "trial": "plan ending soonest",
    "active": "plan ending soonest",
    "expiring": "plan ending soonest",
    "lapsed": "plan most recently ended",
}


def _plan_line(row: Any, *, now: datetime) -> str:
    if row.subscription is not None:
        state = (
            "trial" if row.subscription.status == SubscriptionStatus.TRIAL else "paid"
        )
        return f"{row.subscription.plan.name} ({state}), days left {row.days_left}"
    if row.ended is not None:
        return f"no plan; {row.ended.plan.name} ended {_day(row.ended_on)}"
    return "never had a plan"


def customer_list(db: Session, *, query: CustomerQuery, now: datetime) -> str:
    order = _ORDER.get(query.state, "newest sign-up")
    page = customer_page(
        db,
        now=now,
        narrowing=Narrowing(
            term=query.term.strip(),
            state=query.state,
            plan=query.plan.strip(),
            joined_from=query.joined_from,
            joined_to=query.joined_to,
        ),
    )
    shown = page.rows[:LIST_ROWS]
    lines = [f"## Customers matched: {page.total}"]
    if page.total > len(shown):
        lines.append(
            f"Only the first {len(shown)} are listed below, "
            f"{order} first; "
            f"the other {page.total - len(shown)} were not read. Say so, and "
            "narrow the filter to see them."
        )
    for row in shown:
        user = row.user
        paid = (
            ", ".join(_money(amount, currency) for currency, amount in row.paid_total)
            or "nothing"
        )
        parts = [
            f"- {user.full_name or '(no name)'} <{user.email}>",
            f"signed up {_day(user.date_joined)}",
            f"plan: {_plan_line(row, now=now)}",
            f"paid in all: {paid}",
            f"campaigns running: {row.running}",
            f"leads: {row.leads}",
        ]
        if row.business is not None and row.business.name:
            parts.insert(1, f"business «{row.business.name}»")
        if row.manager is not None:
            parts.append(f"sales manager: {row.manager.full_name or row.manager.email}")
        if row.trouble is not None:
            parts.append(f"problem: {row.trouble.label}")
        if not user.is_active:
            parts.append("BLOCKED")
        lines.append("; ".join(parts))
    if not page.rows:
        lines.append("Nobody.")
    return "\n".join(lines)


# -- plans ---------------------------------------------------------------------


def plans_summary(db: Session, *, now: datetime) -> str:
    counts: dict[tuple[Any, str], int] = {
        (plan_id, status): int(count)
        for plan_id, status, count in db.execute(
            select(Subscription.plan_id, Subscription.status, func.count())
            .join(User, User.id == Subscription.owner_id)
            .where(
                and_(
                    Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
                    Subscription.expires_at > now,
                    User.is_staff.is_(False),
                    not_demo(User.id),
                )
            )
            .group_by(Subscription.plan_id, Subscription.status)
        )
    }
    plans = list(
        db.scalars(select(Plan).order_by(Plan.is_active.desc(), Plan.sort_order))
    )
    if not plans:
        return "## Plans\nNo plans."
    lines = ["## Plans"]
    for plan in plans:
        trial = counts.get((plan.id, SubscriptionStatus.TRIAL), 0)
        paying = counts.get((plan.id, SubscriptionStatus.ACTIVE), 0)
        lines.append(
            f"- {plan.name} (code `{plan.code}`): "
            f"{_money(plan.price, plan.currency)} for {plan.period_days} days"
            f"{', one-time' if plan.is_one_time else ''}"
            f"{'' if plan.is_active else ', withdrawn from sale'}; "
            f"on it now: {trial} on trial, {paying} paying"
        )
    on_trial = sum(
        count
        for (_, status), count in counts.items()
        if status == SubscriptionStatus.TRIAL
    )
    paying_now = sum(
        count
        for (_, status), count in counts.items()
        if status == SubscriptionStatus.ACTIVE
    )
    lines.append(f"- In all now: {on_trial} on trial, {paying_now} paying")
    return "\n".join(lines)


__all__ = [
    "customer_list",
    "customers_summary",
    "latest_payments",
    "money_summary",
    "plans_summary",
    "platform_activity",
    "sales_by_manager",
    "waiting_now",
    "window_of",
]
