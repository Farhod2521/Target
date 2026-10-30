"""The campaigns list, joined with its figures and filtered, in one answer.

The browser used to read the list and the figures apart, join them by id,
read the amounts back out of their words and filter the rows itself; all of
that happens here now, on the numbers.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final, Literal

from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.contract import money, zero_or
from app.modules.accounts.models import User
from app.modules.ads import selectors
from app.modules.ads.contract.words import (
    RUNNING,
    Goal,
    audience_of,
    controls_of,
    goal_of,
    kind_of,
    last_action_of,
    learning_of,
    network_of,
    status_of,
)

Period = Literal["today", "7d", "30d", "90d", "custom"]
StatusFilter = Literal["running", "paused", "all"]
SourceFilter = Literal["all", "here", "network", "other_account"]

# The figures' own period words, by the screen's.
PERIODS: Final[dict[str, str]] = {"today": "today", "7d": "7", "30d": "30", "90d": "90"}
# How far back figures go: the custom range's earliest day.
EARLIEST_DAYS: Final = 89
REASONS: Final = frozenset({"unusable", "rate_limited", "busy", "truncated"})
# A refresh that outran its wait: said under the clock for this long.
LATE_KEY: Final = "campaigns-sync-late:{user}"
LATE_SECONDS: Final = 60


@dataclass(frozen=True, slots=True)
class ListAsk:
    period: Period = "7d"
    status: StatusFilter = "all"
    source: SourceFilter = "all"
    network: str = "all"
    since: date | None = None
    until: date | None = None
    started: str = ""


def figures_range(
    db: Session, *, owner: User, account: Any, ask: ListAsk
) -> tuple[Any, date]:
    """The figures' days, and the cabinet's today they end on."""
    from app.modules.metrics.routers import resolve_range
    from app.modules.metrics.selectors.dashboard import cabinet_today

    today = cabinet_today(db, owner=owner, account=account)
    if ask.period == "custom" and ask.since and ask.until:
        found = resolve_range(period="", start=ask.since, end=ask.until, today=today)
    else:
        found = resolve_range(
            period=PERIODS.get(ask.period, "7"), start=None, end=None, today=today
        )
    return found, today


def figures_of(chips: Any, *, currency: str, provider: str) -> dict[str, Any] | None:
    """Results, the price of one and the spend, from one row's chips."""
    if chips is None or not chips.chips:
        return None
    by_key = {chip.key: chip.value for chip in chips.chips}
    cost = by_key.get("cpl")
    return {
        "results": int(by_key.get("leads") or 0),
        "unit_cost": money(
            int(cost) if cost is not None else None, currency, provider=provider
        ),
        "spent": zero_or(int(by_key.get("spend") or 0), currency, provider=provider),
    }


def campaign_row(
    row: Any, *, goal: Goal, chips: Any, here: frozenset[str]
) -> dict[str, Any]:
    settings = row.settings
    currency = settings.currency or row.currency or row.ad_account.currency
    provider = row.provider
    early = int(getattr(row, "early_hours", 0) or 0)
    learning = learning_of(early)
    controls = getattr(row, "controls", None)
    groups = max(len(row.adsets), settings.groups)
    daily = (
        row.daily_budget_minor
        if row.daily_budget_minor is not None
        else settings.daily_budget_minor
        if settings.daily_budget_minor is not None
        else getattr(controls, "daily_budget_minor", None)
    )
    origin = (
        "other_account"
        if getattr(controls, "watched_account", False)
        else "here"
        if row.external_id in here
        else "network"
    )
    created = row.created_time.isoformat() if row.created_time else ""
    return {
        "id": str(row.id),
        "external_id": row.external_id,
        "name": row.name,
        "goal": goal,
        "kind": kind_of(goal, row.objective_raw or ""),
        "status": status_of(row, learning=learning is not None),
        "network": network_of(provider),
        "origin": origin,
        "daily_budget": zero_or(daily, currency, provider=provider),
        "audience": audience_of(settings.audience),
        "ends_at": settings.ends_at.isoformat() if settings.ends_at else None,
        "total_limit": money(row.spend_cap_minor, currency, provider=provider),
        "metrics": figures_of(chips, currency=currency, provider=provider),
        "quiet_days": chips.quiet_days if chips is not None else None,
        "learning": learning,
        "sending": bool(getattr(row, "pending", False)) or None,
        "problem": getattr(row, "issue_summary", "") or None,
        "deleting": bool(getattr(row, "deleting", False)) or None,
        "last_action": last_action_of(getattr(row, "last_action", None)),
        "group_count": groups if groups > 1 else None,
        "controls": controls_of(controls, early_hours=early),
        # Not counted on the list: the delete question does not say «0 ta».
        "ad_count": None,
        "created_at": created,
        "launched_at": settings.starts_at.isoformat()
        if settings.starts_at
        else created,
    }


def campaign_list(db: Session, *, owner: User, ask: ListAsk) -> dict[str, Any]:
    """Everything the list screen draws, for the filters asked."""
    from app.modules.businesses.selectors import business_for_page
    from app.modules.integrations.selectors import is_connected
    from app.modules.metrics.selectors import accounts_synced_at
    from app.modules.metrics.selectors import has_cooled as figures_cooled
    from app.modules.metrics.selectors.panel import campaign_chips, spend_total

    advertising = selectors.page_advertising(db, owner=owner)
    account = advertising.home
    rows = selectors.campaigns_for(
        db, owner=owner, external_ids=advertising.campaign_ids
    )
    rows = selectors.with_switches(db, owner=owner, campaigns=rows)
    rows = selectors.with_settings(campaigns=rows)
    rows = selectors.with_badges(db, owner=owner, rows=rows)
    business = (
        business_for_page(db, owner=owner, page=advertising.page)
        if advertising.page is not None
        else None
    )
    goals = selectors.by_goal(
        db,
        owner=owner,
        rows=rows,
        category=business.category if business is not None else "",
        provider=advertising.page.provider if advertising.page else "",
    )
    goal_by_id = {str(row.id): group.goal for group in goals for row in group.rows}
    label_by_id = {
        str(row.id): str(group.label) for group in goals for row in group.rows
    }
    chosen, today = figures_range(db, owner=owner, account=account, ask=ask)
    chips = {
        found.campaign_id: found
        for found in campaign_chips(
            db, owner=owner, campaigns=rows, date_range=chosen, account=account
        )
    }
    every = [
        campaign_row(
            row,
            goal=goal_of(goal_by_id.get(str(row.id), row.objective_raw or "")),
            chips=chips.get(str(row.id)),
            here=advertising.here,
        )
        for row in rows
    ]
    by_network = [row for row in every if ask.network in ("all", row["network"]["id"])]
    source = ask.source
    pool = [row for row in by_network if source in ("all", row["origin"])]
    fallback = not pool and source != "all" and bool(by_network)
    if fallback:
        source, pool = "all", by_network
    live = [row for row in pool if row["status"] in RUNNING]
    shown = [
        row
        for row in pool
        if ask.status == "all"
        or (ask.status == "running") == (row["status"] in RUNNING)
    ]
    currency = (
        account.currency
        if account is not None
        else (pool[0]["daily_budget"].currency if pool else "USD")
    )
    whole = ask.network == "all" and source == "all"
    on_air, _ = selectors.split_running(campaigns=rows)
    total_daily, _ = selectors.daily_total(
        settings=[row.settings for row in on_air], currency=currency
    )
    spent_whole = spend_total(
        db, owner=owner, campaigns=rows, date_range=chosen, currency=currency
    )
    synced_at = selectors.last_synced_at(db, owner=owner, accounts=advertising.accounts)
    connected = is_connected(db, owner=owner)
    progress = selectors.sync_progress(
        ad_account_ids=[row.id for row in advertising.accounts]
    )
    reading = progress.known and progress.in_flight
    return {
        "state": "not_connected"
        if not connected
        else "reading"
        if reading and not rows
        else "ready",
        "reading_from": network_of(rows[0].provider)["name"] if rows else "Meta",
        "updated_at": (synced_at.isoformat() if synced_at else ""),
        "sync": _sync(owner, synced_at=synced_at, progress=progress),
        "auto_refresh": account is not None
        and connected
        and not reading
        and (
            selectors.has_cooled(synced_at=synced_at)
            or figures_cooled(
                synced_at=accounts_synced_at(
                    db, owner=owner, accounts=advertising.accounts
                )
            )
        ),
        "access": access_of(db, owner=owner),
        "unplaced": advertising.unplaced,
        "source_fallback": fallback,
        "sources": {
            "all": len(by_network),
            "here": sum(row["origin"] == "here" for row in by_network),
            "network": sum(row["origin"] == "network" for row in by_network),
            "other_account": sum(
                row["origin"] == "other_account" for row in by_network
            ),
        },
        "range": {
            "since": chosen.since.isoformat(),
            "until": chosen.until.isoformat(),
            "earliest": (today - timedelta(days=EARLIEST_DAYS)).isoformat(),
            "today": today.isoformat(),
            "time_zone": (account.timezone or None) if account is not None else None,
        },
        "started": _started(every, ask=ask, page=advertising.page, labels=label_by_id),
        "summary": {
            "daily_budget": zero_or(total_daily, currency)
            if whole
            else zero_or(sum(row["daily_budget"].minor for row in live), currency),
            "spent": zero_or(spent_whole, currency)
            if whole
            else zero_or(
                sum(
                    row["metrics"]["spent"].minor
                    for row in pool
                    if row["metrics"] is not None
                ),
                currency,
            ),
            "running": len(live),
        },
        "trial": _trial(db, owner=owner),
        "draft": None,
        "counts": {
            "running": len(live),
            "paused": len(pool) - len(live),
            "all": len(pool),
        },
        "total": len(every),
        "campaigns": shown,
    }


def _sync(owner: User, *, synced_at: Any, progress: Any) -> dict[str, Any]:
    failure = progress.failure if progress.known and not progress.in_flight else ""
    word = (failure if failure in REASONS else "other") if failure else None
    return {
        "synced_at": synced_at.isoformat() if synced_at else None,
        "stale": selectors.is_stale(synced_at=synced_at),
        "failure": word if word and not progress.succeeded else None,
        "partial": word if word and progress.succeeded else None,
        "late": bool(cache.get(LATE_KEY.format(user=owner.id))) or None,
    }


def access_of(db: Session, *, owner: User) -> dict[str, Any]:
    from app.modules.billing.selectors import has_ever_subscribed, live_subscription

    live = live_subscription(db, owner=owner)
    lapse = None
    if live is None and has_ever_subscribed(db, owner=owner):
        hold = selectors.open_hold(db, owner=owner)
        if hold is not None:
            lapse = hold.delete_after.date().isoformat()
    return {"read_only": live is None, "lapse_until": lapse}


def _started(
    rows: list[dict[str, Any]], *, ask: ListAsk, page: Any, labels: dict[str, str]
) -> dict[str, Any] | None:
    if not ask.started:
        return None
    ours = sorted(
        (row for row in rows if row["origin"] == "here"),
        key=lambda row: row["created_at"],
        reverse=True,
    )
    if not ours:
        return None
    fresh = ours[0]
    return {
        "campaign_id": fresh["id"],
        "business": page.name if page is not None else "",
        "goal": labels.get(fresh["id"], ""),
        "budget": fresh["daily_budget"],
        "first": ask.started == "first",
    }


def _trial(db: Session, *, owner: User) -> dict[str, Any] | None:
    from app.modules.billing.constants import TRIAL_MAX_CAMPAIGNS
    from app.modules.billing.selectors import sellable_plans

    left = selectors.trial_campaigns_left(db, owner=owner)
    if left is None:
        return None
    paid = sorted(
        (
            plan
            for plan in sellable_plans(db, owner=owner)
            if plan.price > 0 and "trial" not in plan.code.lower()
        ),
        key=lambda plan: plan.price,
    )
    offer = None
    if paid:
        cheapest = paid[0]
        # A plan's price is whole units of its currency, not minor ones.
        offer = {
            "name": cheapest.name,
            "price": {
                "minor": int(cheapest.price),
                "currency": cheapest.currency,
                "exponent": 0,
            },
            "days": cheapest.period_days,
        }
    return {"limit": max(TRIAL_MAX_CAMPAIGNS, left), "left": left, "offer": offer}


__all__ = [
    "ListAsk",
    "access_of",
    "campaign_list",
    "campaign_row",
    "figures_of",
    "figures_range",
]
