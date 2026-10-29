"""The office's first screen, as JSON.

Support, Finance and the Owner open it. The money - takings, who just
paid, what the assistant cost - is Finance's and the Owner's: for the
others those blocks are ``null``, and ``/dashboard/takings`` answers 404.
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import Db
from app.common.dates import localtime
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ADMIN_ROLES, MONEY_ROLES, Severity
from app.modules.backoffice.permissions import has_role, staff_required
from app.modules.backoffice.routers._out import amounts, choices, person_out
from app.modules.backoffice.schemas import DashboardOut, TakingsOut
from app.modules.backoffice.selectors.dashboard import (
    PERIODS,
    Slice,
    Takings,
    Window,
    activity,
    asked_window,
    customers,
    recent_payments,
    sales,
    takings,
    waiting,
)
from app.modules.backoffice.selectors.problems import problems

router = APIRouter(prefix="/dashboard")
Admin = Annotated[User, Depends(staff_required(*ADMIN_ROLES))]
Money = Annotated[User, Depends(staff_required(*MONEY_ROLES))]
SHOWN_PROBLEMS = 6

PERIOD_Q = Query("30", description="`today`, `7`, `30`, `month`, `year`, `range`.")
SINCE_Q = Query(None, description="`range`: the first day, YYYY-MM-DD.")
UNTIL_Q = Query(None, description="`range`: the last day, YYYY-MM-DD.")


def _today() -> date:
    return localtime(utcnow()).date()


def _window(*, period: str, since: date | None, until: date | None) -> Window:
    return asked_window(period=period, since=since, until=until, today=_today())


def window_out(window: Window) -> dict[str, Any]:
    return {
        "period": window.period,
        "unit": window.unit,
        "since": window.start,
        "until": window.end,
        "days": window.days,
        "refused": window.refused,
        "periods": choices(PERIODS),
    }


def slice_out(part: Slice) -> dict[str, Any]:
    return {
        "amount_minor": part.amount_minor,
        "payments": part.payments,
        "signups": part.signups,
        "average_minor": part.average_minor,
        "online_minor": part.online_minor,
        "manual_minor": part.manual_minor,
        "plans": [
            {
                "name": plan.name,
                "payments": plan.payments,
                "amount_minor": plan.amount_minor,
                "share_pct": plan.share_pct,
            }
            for plan in part.plans
        ],
    }


def takings_out(found: Takings, *, bar: str = "") -> dict[str, Any]:
    picked = next((row for row in found.bars if row.key == bar), None)
    return {
        "window": window_out(found.window),
        "currency": found.currency,
        "bars": [
            {
                "key": row.key,
                "label": row.label,
                "hint": row.hint,
                "height_pct": row.height_pct,
                "is_current": row.is_current,
                "amount_minor": row.figures.amount_minor,
                "payments": row.figures.payments,
                "signups": row.figures.signups,
            }
            for row in found.bars
        ],
        "picked": picked.key if picked else "",
        "shown": slice_out(picked.figures if picked else found.whole),
        "before_minor": found.before_minor,
        "change_pct": found.change_pct,
        "unpaid": found.unpaid,
        "unpaid_minor": found.unpaid_minor,
        "given_free": found.given_free,
    }


@router.get("", responses={200: {"model": DashboardOut}})
def dashboard(
    db: Db,
    user: Admin,
    period: str = PERIOD_Q,
    since: date | None = SINCE_Q,
    until: date | None = UNTIL_Q,
) -> dict[str, Any]:
    """The whole first screen for one window of days."""
    now = utcnow()
    window = _window(period=period, since=since, until=until)
    sees_money = has_role(db, user, MONEY_ROLES)
    found = problems(db, now=now)
    people = customers(db, window=window, now=now)
    done = activity(db, window=window)
    queues = waiting(db, now=now)
    return {
        "window": window_out(window),
        "sees_money": sees_money,
        "takings": (
            takings_out(takings(db, window=window, today=_today()))
            if sees_money
            else None
        ),
        "customers": {
            "total": people.total,
            "joined": people.joined,
            "joined_before": people.joined_before,
            "joined_change_pct": people.joined_change_pct,
            "trial": people.trial,
            "paying": people.paying,
            "expiring": people.expiring,
            "churned": people.churned,
            "joined_paid": people.joined_paid,
            "conversion_pct": people.conversion_pct,
            "setup_unfinished": people.setup_unfinished,
            "meta_missing": people.meta_missing,
        },
        "activity": {
            "running": done.running,
            "launched": done.launched,
            "failed": done.failed,
            "spend": amounts(done.spend),
            "leads": done.leads,
            "leads_before": done.leads_before,
            "leads_change_pct": done.leads_change_pct,
            "ai_cost": (
                {"currency": done.ai_currency, "amount_minor": done.ai_cost_minor}
                if sees_money
                else None
            ),
        },
        "waiting": {
            "promos": queues.promos,
            "support": queues.support,
            "support_oldest": queues.support_oldest,
            "asks": queues.asks,
            "feedback": queues.feedback,
            "arizas": queues.arizas,
            "holds": queues.holds,
        },
        "problems": {
            "total": len(found),
            "urgent": sum(1 for p in found if p.severity == Severity.URGENT),
            "rows": [
                {
                    "kind": p.kind,
                    "label": p.label,
                    "urgent": p.severity == Severity.URGENT,
                    "customer_id": str(p.owner_id) if p.owner_id else None,
                    "who": p.who,
                    "what": p.what,
                    "since": p.since,
                    "action": p.action,
                }
                for p in found[:SHOWN_PROBLEMS]
            ],
        },
        "payments": (
            [
                {
                    "paid_at": row.paid_at,
                    "customer": person_out(row.customer),
                    "email": row.email,
                    "plan": row.plan,
                    "amount_minor": row.amount_minor,
                    "currency": row.currency,
                    "manual": row.manual,
                }
                for row in recent_payments(db)
            ]
            if sees_money
            else None
        ),
        "sales": [
            {"manager": person_out(row.manager), "sold": row.sold, "open": row.open}
            for row in sales(db, window=window)
        ],
    }


@router.get("/takings", responses={200: {"model": TakingsOut}})
def dashboard_takings(
    db: Db,
    user: Money,
    period: str = PERIOD_Q,
    since: date | None = SINCE_Q,
    until: date | None = UNTIL_Q,
    bar: str = Query(
        "",
        description="A bar's `key`: its figures in `shown`; unknown reads the whole.",
    ),
) -> dict[str, Any]:
    """Only the money card: a filter or a bar pressed swaps it alone."""
    window = _window(period=period, since=since, until=until)
    return takings_out(takings(db, window=window, today=_today()), bar=bar)
