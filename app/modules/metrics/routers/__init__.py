"""The cabinet's numbers: the dashboard figures, refreshing them, the cards."""

from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.cache import cache
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.metrics.constants import (
    DEFAULT_PERIOD,
    MAX_SYNC_POLLS,
    RANGE_MAX_DAYS,
    SYNC_POLL_SECONDS,
    Period,
)
from app.modules.metrics.ranges import CUSTOM, Range, preset_range

router = APIRouter(prefix="/metrics", tags=["metrics"])
FILTERS_KEY = "metrics:numbers_filters:{user}"
FILTERS_SECONDS = 90 * 24 * 60 * 60


def resolve_range(
    *, period: str, start: date | None, end: date | None, today: date
) -> Range:
    if start and end:
        since = max(start, today - timedelta(days=RANGE_MAX_DAYS - 1))
        until = min(end, today)
        if since <= until:
            return Range(since=since, until=until, key=CUSTOM)
        return preset_range(DEFAULT_PERIOD, today=today)
    if period not in Period.values:
        period = DEFAULT_PERIOD
    return preset_range(period, today=today)


def _filters(
    user: User, *, period: str | None, start: date | None, end: date | None, today: date
) -> Range:
    """The asked range, or the last one this reader asked for."""
    key = FILTERS_KEY.format(user=user.id)
    if period is None and start is None and end is None:
        kept = cache.get(key) or {}
        period = kept.get("period", "")
        start = date.fromisoformat(kept["start"]) if kept.get("start") else None
        end = date.fromisoformat(kept["end"]) if kept.get("end") else None
        return resolve_range(period=period or "", start=start, end=end, today=today)
    chosen = resolve_range(period=period or "", start=start, end=end, today=today)
    remembered = (
        {"start": chosen.since.isoformat(), "end": chosen.until.isoformat()}
        if chosen.key == CUSTOM
        else {"period": str(chosen.key)}
    )
    cache.set(key, remembered, timeout=FILTERS_SECONDS)
    return chosen


def _crm_qualified(
    db: Session, *, owner: User, page: Any, since: date, until: date
) -> int | None:
    from app.modules.crm.selectors import crm_open, qualified_count

    if not crm_open(db, owner=owner):
        return None
    zone = page.home.tzinfo() if page.home else None
    start = datetime.combine(since, time.min).replace(tzinfo=zone)
    end = datetime.combine(until + timedelta(days=1), time.min).replace(tzinfo=zone)
    return qualified_count(
        db, owner=owner, since=start, until=end, campaign_ids=page.ids
    )


def numbers_context(
    db: Session,
    user: User,
    *,
    period: str | None = None,
    start: date | None = None,
    end: date | None = None,
    syncing: bool = False,
    tries: int = 0,
) -> dict[str, Any]:
    from app.modules.metrics.selectors import (
        accounts_synced_at,
        figures_are_stale,
        figures_behind_since,
        has_cooled,
    )
    from app.modules.metrics.selectors.dashboard import cabinet_today, dashboard
    from app.modules.metrics.selectors.scope import page_campaigns

    page = page_campaigns(db, owner=user)
    account = page.home
    chosen = _filters(
        user,
        period=period,
        start=start,
        end=end,
        today=cabinet_today(db, owner=user, account=account),
    )
    synced_at = accounts_synced_at(db, owner=user, accounts=page.accounts)
    now = utcnow()
    return {
        "crm_qualified": _crm_qualified(
            db, owner=user, page=page, since=chosen.since, until=chosen.until
        ),
        "dashboard": jsonable_encoder(
            dashboard(db, owner=user, date_range=chosen, page=page, synced_at=synced_at)
        ),
        "filters": {
            "key": str(chosen.key),
            "since": chosen.since,
            "until": chosen.until,
            "days": chosen.days,
            "is_custom": chosen.key == CUSTOM,
            "earliest": utcnow().date() - timedelta(days=RANGE_MAX_DAYS - 1),
        },
        "periods": [
            {"value": value, "label": label} for value, label in Period.choices
        ],
        "page": {"name": page.name, "key": page.key, "currency": page.currency},
        "ad_account": (
            {
                "id": str(account.id),
                "name": account.name,
                "currency": account.currency,
                "timezone": account.timezone,
            }
            if account is not None
            else None
        ),
        "synced_at": synced_at,
        "behind_since": figures_behind_since(
            db, owner=user, accounts=page.accounts, now=now
        ),
        "is_stale": figures_are_stale(synced_at=synced_at, now=now),
        "since": synced_at.isoformat() if synced_at else "",
        "syncing": syncing,
        "account_ids": [str(row.id) for row in page.accounts],
        "auto_refresh": account is not None
        and not syncing
        and has_cooled(synced_at=synced_at),
        "tries": tries,
        "poll_seconds": SYNC_POLL_SECONDS,
    }


@router.get("/numbers")
def numbers(
    db: Db,
    user: CurrentUser,
    period: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    return numbers_context(db, user, period=period, start=start, end=end)


@router.get("/numbers/poll")
def numbers_poll(
    db: Db,
    user: CurrentUser,
    since: str | None = None,
    tries: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Asked every few seconds after a refresh, until today's figures land."""
    from app.modules.ads.selectors import today_in_flight

    context = numbers_context(db, user, tries=tries + 1)
    waiting = (
        since is not None
        and since == context["since"]
        and today_in_flight(ad_account_ids=context["account_ids"])
    )
    context["syncing"] = waiting and tries < MAX_SYNC_POLLS
    context["gave_up"] = waiting and not context["syncing"]
    context["since"] = since or ""
    return context


@router.post("/numbers/refresh")
def numbers_refresh(db: Db, user: CurrentUser, on_open: bool = False) -> dict[str, Any]:
    from app.modules.metrics.services import refresh_on_open, request_refresh

    if on_open:
        queued = refresh_on_open(db, user=user)
        db.commit()
        return numbers_context(db, user, syncing=queued)
    request_refresh(db, user=user)
    db.commit()
    return {
        "message": "Yangilanish boshlandi.",
        **numbers_context(db, user, syncing=True),
    }


@router.get("/cards")
def cards(db: Db, user: CurrentUser) -> dict[str, Any]:
    from app.modules.metrics.selectors.card_kinds import RESULT_KEYS, text_of
    from app.modules.metrics.selectors.cards import GROUP_TEXT, chosen_for
    from core.metrics import CARDS, GROUPS, ROW_KEYS

    chosen = set(chosen_for(db, owner=user))
    return {
        "groups": [
            {
                "key": group,
                "label": GROUP_TEXT[group],
                "cards": [
                    {
                        "key": card.key,
                        "label": text_of(card).label,
                        "hint": text_of(card).hint,
                        "is_on": card.key in chosen,
                        "is_on_row": card.key in ROW_KEYS,
                        "is_daily": card.basis == "day",
                        "is_per_goal": card.key in RESULT_KEYS,
                    }
                    for card in CARDS
                    if card.group == group
                ],
            }
            for group in GROUPS
        ],
        "chosen_count": len(chosen),
    }


class CardsIn(BaseModel):
    cards: list[str] = Field(default_factory=list)


@router.post("/cards")
def cards_save(body: CardsIn, db: Db, user: CurrentUser) -> dict[str, Any]:
    from app.modules.metrics.services import save_cards

    chosen = save_cards(db, owner=user, keys=body.cards)
    db.commit()
    return {"message": "Saqlandi.", "chosen": list(chosen)}
