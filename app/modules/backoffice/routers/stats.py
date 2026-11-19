"""The office's Statistika screen, as JSON.

Finance and the Owner open it; everyone else gets 404. One window of days,
the same as the dashboard's; a block that is a state rather than a flow
(the ladder, the businesses, who the customers are) is read as of the
window's end or as of now, and says which.
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import Db
from app.common.dates import localtime
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import MONEY_ROLES
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.routers._out import person_out
from app.modules.backoffice.routers.dashboard import (
    PERIOD_Q,
    SINCE_Q,
    UNTIL_Q,
    window_out,
)
from app.modules.backoffice.schemas import StatsLostOut, StatsOut
from app.modules.backoffice.selectors import stats
from app.modules.backoffice.selectors.dashboard import Window, asked_window

router = APIRouter(prefix="/stats")
Money = Annotated[User, Depends(staff_required(*MONEY_ROLES))]
LOST_SHOWN = 100


def _window(*, period: str, since: date | None, until: date | None) -> Window:
    today = localtime(utcnow()).date()
    return asked_window(period=period, since=since, until=until, today=today)


@router.get("", responses={200: {"model": StatsOut}})
def statistics(
    db: Db,
    user: Money,
    period: str = PERIOD_Q,
    since: date | None = SINCE_Q,
    until: date | None = UNTIL_Q,
) -> dict[str, Any]:
    """The whole Statistika screen for one window of days."""
    now = utcnow()
    window = _window(period=period, since=since, until=until)
    buyers = stats.purchases(db)
    plans = stats.every_plan(db)
    live = stats.live_owner_ids(db, now=now)
    money = stats.money(db, buyers, window=window, now=now)
    currency = money["currency"]
    ai = stats.ai_cost(db, window=window, now=now)
    return {
        "window": window_out(window),
        "headline": stats.headline(
            db,
            buyers,
            window=window,
            currency=currency,
            ai_now=ai["per_customer_month_micros"],
        ),
        "series": stats.series(db, buyers, window=window, currency=currency),
        "statuses": stats.statuses(db, now=now),
        "growth": stats.growth(db, window=window, currency=currency),
        "ladder": stats.ladder(buyers, window=window),
        "plans": stats.plans_sold(buyers, window=window, plans=plans),
        "loyal": stats.loyal(buyers, window=window, live=live, plans=plans),
        "keeping": stats.keeping(buyers, window=window, now=now),
        "start": stats.start_out(
            stats.start_cohort(db, buyers, window=window, now=now)
        ),
        "funnel": stats.funnel(db, buyers, window=window),
        "ai": ai,
        "businesses": stats.businesses(db, window=window, now=now),
        "people": stats.people(db, window=window, now=now),
        "money": money,
        "usage": stats.usage(db, window=window, now=now),
    }


@router.get("/start-lost", responses={200: {"model": StatsLostOut}})
def start_lost(
    db: Db,
    user: Money,
    reason: str = Query(..., description="A `start.lost_reasons[].key`."),
    period: str = PERIOD_Q,
    since: date | None = SINCE_Q,
    until: date | None = UNTIL_Q,
) -> dict[str, Any]:
    """Who stopped after Start for one reason: the customers behind a
    `start.lost_reasons` row, newest sign-up first."""
    if reason not in stats.LOST_LABELS:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    window = _window(period=period, since=since, until=until)
    found = stats.start_cohort(db, stats.purchases(db), window=window, now=utcnow())
    owners = found.lost[reason]
    shown = stats.lost_people(db, owners, limit=LOST_SHOWN)
    return {
        "window": window_out(window),
        "reason": reason,
        "label": stats.LOST_LABELS[reason],
        "total": len(owners),
        "deleted": sum(1 for owner in owners if owner is None),
        "rows": [
            {
                "customer": person_out(person),
                "email": person.email,
                "phone": person.phone,
                "joined_at": person.date_joined,
            }
            for person in shown
        ],
    }
