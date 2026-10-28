"""The actions screen ("Amallar"): everything waiting for an answer, worst first.

``GET /actions`` is the screen: three bands of items (urgent, decisions,
news) - the open proposals drawn apart with their own buttons - the agent's
status line and advice, and the first page of answered proposals.
``POST /actions/bell`` opens the bell: it marks what it shows as seen, so it
is a POST. ``GET /actions/counts`` is the two badges.
"""

from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.ads.selectors.pages import current_page_scope
from app.modules.agent.constants import HISTORY_PAGE, IN_FLIGHT_POLL_SECONDS
from app.modules.agent.models import AgentPolicy
from app.modules.agent.selectors.cards import history_cards
from app.modules.agent.selectors.runs import last
from app.modules.agent.selectors.summary import (
    AdviceCard,
    advice_cards,
    agent_summary,
    proposals,
)
from app.modules.notifications.schemas import (
    ActionsOut,
    BellOut,
    CountsOut,
    HistoryOut,
    ProposalsOut,
)
from app.modules.notifications.selectors import seen_keys
from app.modules.notifications.selectors.bell import (
    PANEL_ITEMS,
    counted,
    counts_for,
    item_to_dict,
    remember,
    watching,
)
from app.modules.notifications.selectors.inbox import inbox
from app.modules.notifications.selectors.inbox_page import inbox_page
from app.modules.notifications.services import mark_seen
from core.inbox import InboxItem, keys, of_level, unseen, without_kind

router = APIRouter(prefix="/actions", tags=["actions"])


def item_out(item: InboxItem) -> dict[str, Any]:
    """One line, with the chat link every line carries."""
    return item_to_dict(item) | {
        "ask": {
            "label": "AI tushuntirib bersin"
            if item.kind == "launch"
            else "AI dan so'rash",
            "href": f"{reverse('chat:chat')}?item={quote(item.key, safe='/')}",
        }
    }


def _policy(row: AgentPolicy | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "is_enabled": row.is_enabled,
        "self_repair": row.self_repair,
        "window_days": row.window_days,
        "cooldown_hours": row.cooldown_hours,
        "max_per_run": row.max_per_run,
        "budget_step_pct": row.budget_step_pct,
        "last_run_at": row.last_run_at,
    }


def _advice(card: AdviceCard) -> dict[str, Any]:
    return {
        "strategy": card.strategy,
        "title": str(card.title),
        "body": str(card.body),
        "href": reverse(card.route),
        "link": str(card.link),
        "ready": card.ready,
        "blocked_by": [str(line) for line in card.blocked_by],
    }


def _proposals(db: Session, *, user: User, now: datetime) -> dict[str, Any]:
    open_ones = proposals(db, owner=user, now=now)
    return {
        "cards": open_ones.cards,
        "policy": _policy(open_ones.policy),
        "counted": open_ones.counted,
        "late": open_ones.late,
        "working": open_ones.working,
        "poll_seconds": IN_FLIGHT_POLL_SECONDS,
    }


def history_page(
    db: Session, *, owner: User, before: datetime | None = None
) -> dict[str, Any]:
    """One page of the record; one extra row read answers whether there is more."""
    found = history_cards(
        db,
        owner=owner,
        limit=HISTORY_PAGE + 1,
        before=before,
        scope=current_page_scope(db, owner=owner),
    )
    page = found[:HISTORY_PAGE]
    more = len(found) > HISTORY_PAGE
    return {
        "history": page,
        "more": more,
        "next_before": page[-1].cursor if more else None,
    }


def _cursor(raw: str) -> datetime | None:
    """A cursor that will not parse is no cursor: the first page again."""
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw.replace(" ", "+"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


@router.get("", responses={200: {"model": ActionsOut}})
def actions_screen(db: Db, user: CurrentUser) -> dict[str, Any]:
    """Everything waiting, in three bands, with the proposals and the record."""
    now = utcnow()
    items = remember(db, owner=user, items=inbox(db, owner=user, now=now))
    rest = without_kind(items, kind="suggestion")
    run = last(db, owner=user)
    view = inbox_page(db, owner=user)
    counts = counted(db, owner=user, items=items)
    return jsonable_encoder(
        _proposals(db, user=user, now=now)
        | {
            "urgent": [item_out(item) for item in of_level(rest, level="urgent")],
            "decisions": [item_out(item) for item in of_level(rest, level="decision")],
            "news": [item_out(item) for item in of_level(rest, level="news")],
            "summary": agent_summary(run=run),
            "advice": [
                _advice(card)
                for card in advice_cards(db, owner=user, run=run, page_id=view.page_id)
            ],
            "counts": {"new": counts.new, "waiting": counts.waiting},
        }
        | history_page(db, owner=user)
    )


@router.post("/bell", responses={200: {"model": BellOut}})
def bell(db: Db, user: CurrentUser) -> dict[str, Any]:
    """What is waiting, six lines of it, the new ones marked - and now seen."""
    items = remember(db, owner=user, items=inbox(db, owner=user, now=utcnow()))
    fresh = {item.key for item in unseen(items, seen=seen_keys(db, owner=user))}
    mark_seen(db, owner=user, keys=keys(items))
    db.commit()
    home = reverse("actions:home")
    return jsonable_encoder(
        {
            "items": [
                item_out(item)
                | {
                    "fresh": item.key in fresh,
                    "link": item.href if item.href and item.method != "post" else home,
                }
                for item in items[:PANEL_ITEMS]
            ],
            "more": max(0, len(items) - PANEL_ITEMS),
            "watching": watching(db, owner=user),
            "all_href": home,
        }
    )


@router.get("/counts", responses={200: {"model": CountsOut}})
def counts(db: Db, user: CurrentUser) -> dict[str, int]:
    """The bell's number and the navigation's. Reads; marks nothing seen."""
    found = counts_for(db, owner=user, now=utcnow())
    return {"new": found.new, "waiting": found.waiting}


@router.get("/history", responses={200: {"model": HistoryOut}})
def history(
    db: Db,
    user: CurrentUser,
    before: str = Query("", description="The previous page's `next_before`."),
) -> dict[str, Any]:
    """The next page of answered proposals."""
    return jsonable_encoder(history_page(db, owner=user, before=_cursor(before)))


@router.get("/proposals", responses={200: {"model": ProposalsOut}})
def proposals_screen(db: Db, user: CurrentUser) -> dict[str, Any]:
    """The open proposals again, for a screen watching a change land."""
    return jsonable_encoder(
        _proposals(db, user=user, now=utcnow()) | history_page(db, owner=user)
    )
