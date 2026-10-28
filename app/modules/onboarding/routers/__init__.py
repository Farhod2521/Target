"""The preparation screen: what is done, what is next, what it is waiting on."""

from typing import Any

from fastapi import APIRouter, Query
from metaads.accounts import billing_url
from metaads.leadforms import terms_url
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.billing.selectors import may_prepare, setup_locked, setup_pending
from app.modules.businesses.selectors import business_for, category_label
from app.modules.integrations import selectors as connections
from app.modules.integrations.schemas import (
    AdAccountOut,
    ConnectionOut,
    InstagramChoiceOut,
    PageOut,
)
from app.modules.integrations.selectors.connection import pages as all_pages
from app.modules.onboarding import services
from app.modules.onboarding.constants import (
    CLOSED_MESSAGE,
    CLOSED_SECTIONS,
    FINISHED_MESSAGE,
    MAX_POLLS,
    POLL_SECONDS,
    START_PATH,
    WATCH_TELEGRAM,
)
from app.modules.onboarding.schemas import GateOut, StartOut
from app.modules.onboarding.selectors import (
    AccountOption,
    PagePick,
    PageRow,
    SetupOverview,
    overview_as_dict,
    page_pick,
    setup_overview,
)

router = APIRouter(prefix="/start", tags=["onboarding"])


def gate(db: Session, *, owner: User) -> dict[str, Any]:
    """Django's onboarding middleware as data: whether to send the reader here."""
    pending = setup_pending(db, owner=owner)
    return {
        "setup_pending": pending,
        "redirect_to": START_PATH,
        "message": CLOSED_MESSAGE if pending else "",
        "closed": list(CLOSED_SECTIONS),
    }


def _account(account: Any) -> dict[str, Any] | None:
    if account is None:
        return None
    return AdAccountOut.model_validate(account).model_dump(mode="json")


def _page(page: Any) -> dict[str, Any] | None:
    if page is None:
        return None
    return PageOut.model_validate(page).model_dump(mode="json")


def _row(row: PageRow | None) -> dict[str, Any] | None:
    if row is None:
        return None
    profile = row.profile
    return {
        "page": _page(row.page),
        "payer": _account(row.payer),
        "profile": {
            "id": str(profile.id),
            "name": profile.name,
            "category": profile.category,
            "category_label": category_label(profile),
        }
        if profile is not None
        else None,
        "problems": list(row.problems),
        "warnings": list(row.warnings),
        "paired": row.paired,
        "ready": row.ready,
    }


def _options(options: tuple[AccountOption, ...]) -> list[dict[str, Any]]:
    return [
        {
            "account": _account(option.account),
            "recommended": option.recommended,
            "unusable": option.unusable,
        }
        for option in options
    ]


def _pick(pick: PagePick) -> dict[str, Any]:
    return {
        "rows": [_row(row) for row in pick.rows],
        "chosen": _row(pick.chosen),
        "options": _options(pick.options),
        "recommended": _options(pick.recommended),
        "others": _options(pick.others),
        "unusable": _options(pick.unusable),
        "any_without_instagram": pick.any_without_instagram,
    }


def _next_action(setup: SetupOverview, *, locked: bool, may_connect: bool) -> str:
    """What the one orange button on the screen does."""
    if not may_connect:
        return "renew"
    if locked and setup.ready:
        return "launch"
    if not locked and setup.can_finish:
        return "finish"
    if setup.blocked_on in ("page", "ad_account"):
        return "pick"
    return setup.blocked_on or "launch"


def _tries(raw: str) -> int:
    """How many times this tab has already asked, clamped rather than believed."""
    try:
        return max(0, min(MAX_POLLS, int(raw)))
    except (TypeError, ValueError):
        return 0


def setup_context(
    db: Session, owner: User, *, tries: int = 0, watch: str = ""
) -> dict[str, Any]:
    from app.modules.notifications.selectors import chat_for

    setup = setup_overview(db, owner=owner)
    active_page = connections.active_page(db, owner=owner)
    active_account = connections.active_ad_account(db, owner=owner)
    telegram = setup.state.get("telegram")
    # Watched only after the button here was pressed, and while still open.
    watching_telegram = watch == WATCH_TELEGRAM and telegram not in (None, "done")
    business = business_for(db, owner)
    locked = setup_locked(db, owner=owner)
    may_connect = may_prepare(db, owner=owner)
    connection = connections.meta_connection(db, owner=owner)
    slots = connections.page_slots(db, owner=owner)
    chat = chat_for(db, owner=owner) if telegram == "done" else None
    return {
        "setup": overview_as_dict(setup),
        "gate": gate(db, owner=owner),
        "pick": _pick(page_pick(db, owner=owner)),
        "next_action": _next_action(setup, locked=locked, may_connect=may_connect),
        "business_label": category_label(business) if business else "",
        "connection": ConnectionOut.model_validate(connection).model_dump(mode="json")
        if connection
        else None,
        "ad_accounts": [
            _account(row) for row in connections.ad_accounts(db, owner=owner)
        ],
        "active_ad_account": _account(active_account),
        "ad_accounts_taken": list(
            connections.ad_accounts_held_elsewhere(db, owner=owner)
        ),
        "pages": [_page(row) for row in all_pages(db, owner=owner)],
        "ig_needs_permission": connections.instagram_permission_missing(
            db, owner=owner
        ),
        "active_page": _page(active_page),
        "spare_pages": [
            {
                "external_id": row.external_id,
                "name": row.name,
                "instagram_username": row.instagram_username,
            }
            for row in connections.pages_on_offer(db, owner=owner)
        ],
        "billing_url": billing_url(active_account.external_id)
        if active_account is not None
        else "",
        "page_terms_url": terms_url(active_page.external_id)
        if active_page is not None
        else "",
        "may_connect": may_connect,
        "account_locked": locked,
        "page_slots": {
            "allowed": slots.allowed,
            "used": slots.used,
            "free": slots.free,
            "has_room": slots.has_room,
        },
        "setup_instagrams": [
            InstagramChoiceOut.model_validate(row).model_dump()
            for row in connections.instagram_choices(db, page=active_page)
        ]
        if active_page is not None
        else [],
        "telegram_chat": {"username": chat.username, "linked_at": chat.linked_at}
        if chat is not None
        else None,
        "watching_telegram": watching_telegram,
        # Keep asking while a step answered elsewhere is open, never past
        # ``MAX_POLLS``.
        "polling": tries < MAX_POLLS
        and (setup.state["leads"] == "current" or watching_telegram),
        "tries": tries + 1,
        "poll_seconds": POLL_SECONDS,
    }


@router.get("", responses={200: {"model": StartOut}})
def start(
    db: Db,
    user: CurrentUser,
    tries: str = Query(
        "0", description="The last answer's `tries` when polling; 0 on first open."
    ),
    watch: str = Query(
        "", description="`telegram` after the link-Telegram button was pressed."
    ),
) -> dict[str, Any]:
    """The steps and what is done; poll it while `polling` is true."""
    return setup_context(db, user, tries=_tries(tries), watch=watch)


@router.get("/gate", responses={200: {"model": GateOut}})
def start_gate(db: Db, user: CurrentUser) -> dict[str, Any]:
    """Whether the cabinet's working screens should send the reader to `/start`."""
    return gate(db, owner=user)


@router.post("/finish", responses={200: {"model": StartOut}})
def finish(db: Db, user: CurrentUser) -> dict[str, Any]:
    """Close preparation; fixes the page and the ad account."""
    services.finish_setup(db, user=user, now=utcnow())
    db.commit()
    return {"message": FINISHED_MESSAGE, **setup_context(db, user)}
