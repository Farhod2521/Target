"""The cabinet's campaigns: the list, one campaign, refreshing the mirror,
and the switches - pause, resume, budget, revert, delete.

A change answers at once with the row's controls and the pending action;
the frontend polls ``/manage/{level}/{external_id}/state`` until it lands.
"""

import uuid
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.cache import cache
from app.common.contract import Camel
from app.common.db import utcnow
from app.common.exceptions import DomainError, InputRefused
from app.common.money import format_minor, provider_money
from app.modules.accounts.models import User
from app.modules.ads import actions, selectors, services
from app.modules.ads.constants import (
    ACTION_POLL_SECONDS,
    DEFAULT_SHOWN,
    LIST_POLL_SECONDS,
    MAX_ACTION_POLLS,
    MAX_SYNC_POLLS,
    ManagedLevel,
    Shown,
)
from app.modules.ads.contract.shapes import (
    CampaignAd,
    CampaignDetail,
    CampaignList,
    CampaignTree,
    ControlState,
)
from app.modules.ads.exceptions import NothingToRevert, PressRefused
from app.modules.ads.schemas import (
    ActionStateOut,
    BudgetFormOut,
    CampaignHistoryOut,
    CampaignPollOut,
    DeletedOut,
    MessageOut,
    SyncOut,
)
from app.modules.ads.selectors.failures import failure_sentence
from app.modules.audit.constants import ActionStatus

router = APIRouter(prefix="/campaigns", tags=["campaigns"])
FILTERS_KEY = "ads:campaign_filters:{user}"
FILTERS_SECONDS = 90 * 24 * 60 * 60

WAITED_Q = Query(0, ge=0, description="The last answer's `waited`.")
TRIES_Q = Query(0, ge=0, description="The last answer's `tries`.")


# -- drawing rows --------------------------------------------------------------------


def _note(note: Any | None) -> dict[str, Any] | None:
    return asdict(note) if note is not None else None


def _action(
    row: Any | None, *, revertible: bool | None = None
) -> dict[str, Any] | None:
    """One change as the screens read it. ``revertible`` is worked out here for
    the latest change on a row - nothing newer can have replaced it - and
    passed in for a history, where it can have been."""
    if row is None:
        return None
    if revertible is None:
        revertible = actions.undoing(row) is not None
    return {
        "id": str(row.id),
        "action": row.action,
        "status": row.status,
        "dry_run": row.dry_run,
        "error_message": failure_sentence(row)
        if row.status == ActionStatus.FAILED
        else row.error_message,
        "created_at": row.created_at,
        "applied_at": row.applied_at,
        "revertible": revertible,
        "dropped": dict(row.dropped or {}),
    }


def _controls(row: Any) -> dict[str, Any] | None:
    found = getattr(row, "controls", None)
    return asdict(found) if found is not None else None


def _base(row: Any) -> dict[str, Any]:
    badge = getattr(row, "badge", None)
    return {
        "id": str(row.id),
        "external_id": row.external_id,
        "provider": row.provider,
        "name": row.name,
        "status": row.status,
        "effective_status": row.effective_status,
        "delivery": row.delivery,
        "badge": str(badge) if badge is not None else row.delivery,
        "badge_label": badge.label if badge is not None else "",
        "issue_summary": getattr(row, "issue_summary", ""),
        "issues": getattr(row, "issues", []),
        "recommendations": getattr(row, "recommendations", []),
        "early_hours": getattr(row, "early_hours", 0),
        "controls": _controls(row),
        "last_action": _action(getattr(row, "last_action", None)),
        "deleting": getattr(row, "deleting", False),
        "delete_failure": _note(getattr(row, "delete_failure", None)),
        "synced_at": row.synced_at,
    }


def ad_out(ad: Any) -> dict[str, Any]:
    content = getattr(ad, "content", None)
    return _base(ad) | {
        "creative_external_id": ad.creative_external_id,
        "review_feedback": ad.review_feedback,
        "is_last": getattr(ad, "is_last", False),
        "content": (
            {
                "kind": content.kind,
                "message": content.message,
                "headline": content.headline,
                "description": content.description,
                "link_url": content.link_url,
                "call_to_action": content.call_to_action,
                "thumbnail_url": content.thumbnail_url,
                "page_id": content.page_id,
            }
            if content is not None
            else None
        ),
    }


def adset_out(adset: Any, campaign: Any, *, with_ads: bool = False) -> dict[str, Any]:
    out = _base(adset) | {
        "daily_budget_minor": adset.daily_budget_minor,
        "currency": adset.currency,
        "optimization_goal": adset.optimization_goal_raw,
        "is_learning": adset.is_learning,
        "learning_status": adset.learning_status,
        "start_time": adset.start_time,
        "end_time": adset.end_time,
        "is_last": getattr(adset, "is_last", False),
        "settings": jsonable_encoder(
            selectors.group_settings(adset=adset, campaign=campaign)
        ),
    }
    if with_ads:
        out["ads"] = [ad_out(ad) for ad in getattr(adset, "fold_ads", adset.ads)]
    return out


def campaign_out(
    campaign: Any, *, here: frozenset[str] = frozenset()
) -> dict[str, Any]:
    account = campaign.ad_account
    settings = getattr(campaign, "settings", None)
    return _base(campaign) | {
        "objective": campaign.objective_raw,
        "daily_budget_minor": campaign.daily_budget_minor,
        "spend_cap_minor": campaign.spend_cap_minor,
        "currency": campaign.currency or (account.currency if account else ""),
        "created_time": campaign.created_time,
        "adset_count": getattr(campaign, "adset_count", len(campaign.adsets)),
        "built_here": campaign.external_id in here,
        "pending": getattr(campaign, "pending", False),
        "settings": jsonable_encoder(settings) if settings is not None else None,
        "ad_account": (
            {
                "id": str(account.id),
                "name": account.name,
                "external_id": account.external_id,
            }
            if account is not None
            else None
        ),
    }


# -- the list ---------------------------------------------------------------------------


def _filters(user: User, *, show: str | None, source: str | None) -> tuple[str, str]:
    from app.modules.metrics.constants import DEFAULT_SOURCE, Source

    key = FILTERS_KEY.format(user=user.id)
    kept = cache.get(key) or {}
    shown = show if show is not None else kept.get("show", DEFAULT_SHOWN)
    picked = source if source is not None else kept.get("source", DEFAULT_SOURCE)
    shown = shown if shown in Shown.values else DEFAULT_SHOWN
    picked = picked if picked in Source.values else DEFAULT_SOURCE
    if show is not None or source is not None:
        cache.set(key, {"show": shown, "source": picked}, timeout=FILTERS_SECONDS)
    return shown, picked


def campaigns_context(
    db: Session,
    user: User,
    *,
    show: str | None = None,
    source: str | None = None,
    syncing: bool = False,
    tries: int = 0,
    waited: int = 0,
) -> dict[str, Any]:
    from app.modules.businesses.selectors import business_for_page
    from app.modules.integrations.selectors import is_connected
    from app.modules.metrics.constants import Source
    from app.modules.metrics.selectors import accounts_synced_at
    from app.modules.metrics.selectors import has_cooled as figures_cooled

    advertising = selectors.page_advertising(db, owner=user)
    account = advertising.home
    rows = selectors.campaigns_for(
        db, owner=user, external_ids=advertising.campaign_ids
    )
    rows = selectors.with_switches(db, owner=user, campaigns=rows)
    rows = selectors.with_settings(campaigns=rows)
    rows = selectors.with_badges(db, owner=user, rows=rows)
    shown, picked = _filters(user, show=show, source=source)
    here = [row for row in rows if row.external_id in advertising.here]
    elsewhere = [row for row in rows if row.external_id not in advertising.here]
    running, stopped = selectors.split_running(campaigns=rows)
    pool = {Source.HERE: here, Source.ELSEWHERE: elsewhere}.get(picked, rows)
    source_fallback = not pool and picked != Source.ALL and bool(rows)
    if source_fallback:
        picked, pool = Source.ALL, rows
    on_air, off_air = selectors.split_running(campaigns=pool)
    total, currency = selectors.daily_total(
        settings=[row.settings for row in on_air],
        currency=account.currency if account else "",
    )
    listed = {Shown.RUNNING: on_air, Shown.STOPPED: off_air}.get(shown, pool)
    business = (
        business_for_page(db, owner=user, page=advertising.page)
        if advertising.page is not None
        else None
    )
    groups = selectors.by_goal(
        db,
        owner=user,
        rows=listed,
        category=business.category if business is not None else "",
        provider=advertising.page.provider if advertising.page else "",
    )
    synced_at = selectors.last_synced_at(db, owner=user, accounts=advertising.accounts)
    connected = is_connected(db, owner=user)
    return {
        "campaigns": [campaign_out(row, here=advertising.here) for row in listed],
        "goal_groups": [
            {
                "goal": group.goal,
                "label": str(group.label),
                "campaign_ids": [str(row.id) for row in group.rows],
            }
            for group in groups
        ],
        "counts": {
            "running": len(running),
            "stopped": len(stopped),
            "here": len(here),
            "elsewhere": len(elsewhere),
            "unplaced": advertising.unplaced,
            "pool": len(pool),
            "total": len(rows),
        },
        "shown": shown,
        "source": picked,
        "source_fallback": source_fallback,
        "tabs": [{"key": k, "label": v} for k, v in Shown.choices],
        "source_tabs": [{"key": k, "label": v} for k, v in Source.choices],
        "daily_total_minor": total,
        "daily_total_currency": currency,
        "ad_account": (
            {"id": str(account.id), "name": account.name, "currency": account.currency}
            if account is not None
            else None
        ),
        "shown_page": (
            {"id": str(advertising.page.id), "name": advertising.page.name}
            if advertising.page is not None
            else None
        ),
        "is_connected": connected,
        "synced_at": synced_at,
        "is_stale": selectors.is_stale(synced_at=synced_at),
        "since": synced_at.isoformat() if synced_at else "",
        "syncing": syncing,
        "sync_account_ids": [str(row.id) for row in advertising.accounts],
        "auto_refresh": (
            account is not None
            and connected
            and not syncing
            and (
                selectors.has_cooled(synced_at=synced_at)
                or figures_cooled(
                    synced_at=accounts_synced_at(
                        db, owner=user, accounts=advertising.accounts
                    )
                )
            )
        ),
        "tries": tries,
        "retries_left": max(0, MAX_SYNC_POLLS - tries),
        "watching": any(getattr(row, "pending", False) for row in rows)
        and waited < MAX_ACTION_POLLS,
        "waited": waited + 1,
        "list_poll_seconds": LIST_POLL_SECONDS,
        "trial_campaigns_left": selectors.trial_campaigns_left(db, owner=user),
    }


def _pick(value: str | None, allowed: tuple[str, ...], default: str) -> Any:
    return value if value in allowed else default


@router.get("", response_model=CampaignList)
def campaign_list(
    db: Db,
    user: CurrentUser,
    period: str | None = Query(
        None, description="`today`, `7d`, `30d`, `90d`, `custom`."
    ),
    status: str | None = Query(None, description="`running`, `paused` or `all`."),
    source: str | None = Query(
        None, description="`all`, `here`, `network` or `other_account`."
    ),
    network: str = Query("all", description="A network id, or `all`."),
    since: date | None = Query(None, description="`custom`: the first day."),
    until: date | None = Query(None, description="`custom`: the last day."),
    started: str = Query(
        "", description="Set by the launch that just started: `1`, or `first`."
    ),
) -> dict[str, Any]:
    """The list as the screen draws it: rows with their figures, filtered, and its totals."""
    from app.modules.ads.contract.listing import ListAsk
    from app.modules.ads.contract.listing import campaign_list as listed

    ask = ListAsk(
        period=_pick(period, ("today", "7d", "30d", "90d", "custom"), "7d"),
        status=_pick(status, ("running", "paused", "all"), "all"),
        source=_pick(source, ("all", "here", "network", "other_account"), "all"),
        network=network or "all",
        since=since,
        until=until,
        started=started,
    )
    return listed(db, owner=user, ask=ask)


@router.get("/poll", responses={200: {"model": CampaignPollOut}})
def campaign_poll(
    db: Db,
    user: CurrentUser,
    since: str | None = Query(
        None, description="The list's `since` from before the refresh."
    ),
    accounts: str = Query(
        "", description="The list's `sync_account_ids`, joined with commas."
    ),
    tries: int = TRIES_Q,
    waited: int = WAITED_Q,
) -> dict[str, Any]:
    """Asked after a refresh: ``waiting`` true until the mirror and today's figures land."""
    if (
        since is not None
        and tries < MAX_SYNC_POLLS
        and selectors.still_waiting(
            db, owner=user, account_ids=accounts.split(","), since=since
        )
    ):
        return {
            "waiting": True,
            "tries": tries + 1,
            "retries_left": max(0, MAX_SYNC_POLLS - tries - 1),
        }
    context = campaigns_context(db, user, tries=tries + 1, waited=waited)
    if since is not None:
        ids = context["sync_account_ids"]
        progress = selectors.sync_progress(ad_account_ids=ids)
        waiting = (
            since == context["since"] and (progress.in_flight or not progress.known)
        ) or (selectors.today_in_flight(ad_account_ids=ids))
        failure = progress.failure if not waiting and progress.known else ""
        syncing = waiting and tries < MAX_SYNC_POLLS
        context |= {
            "syncing": syncing,
            "gave_up": waiting and not syncing,
            "still_running": waiting and not syncing and progress.in_flight,
            "sync_failure": failure if not progress.succeeded else "",
            "sync_partial": failure if progress.succeeded else "",
        }
    return {"waiting": False, **context}


@router.post("/sync", responses={200: {"model": SyncOut}})
def campaign_sync(
    db: Db,
    user: CurrentUser,
    on_open: bool = Query(
        False,
        description="True when the list asked for it (`auto_refresh`): refreshes "
        "only what has gone stale.",
    ),
) -> dict[str, Any]:
    from app.modules.metrics.services import refresh_on_open, request_refresh

    if on_open:
        mirror = services.sync_on_open(db, user=user)
        today = refresh_on_open(db, user=user)
        db.commit()
        if not (mirror or today):
            return {"queued": False}
        return {"queued": True, **campaigns_context(db, user, syncing=True)}
    services.request_sync(db, user=user)
    request_refresh(db, user=user)
    db.commit()
    return {
        "queued": True,
        "message": "Yangilanish boshlandi.",
        **campaigns_context(db, user, syncing=True),
    }


# -- one campaign ---------------------------------------------------------------------------


def _detail(db: Session, user: User, campaign_id: uuid.UUID) -> Any:
    campaign = selectors.campaign_detail(db, owner=user, campaign_id=campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return campaign


def _groups(db: Session, user: User, campaign: Any) -> list[Any]:
    groups = list(campaign.adsets)
    ads = selectors.with_content(
        db, owner=user, ads=[ad for adset in groups for ad in adset.ads]
    )
    for adset in groups:
        adset.fold_ads = [ad for ad in ads if ad.adset_id == adset.id]
    return groups


@router.get("/{campaign_id}", response_model=CampaignDetail)
def campaign_detail(
    campaign_id: uuid.UUID, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """One campaign's page: its figures, adverts, groups and history in one answer."""
    from app.modules.ads.contract.detail import campaign_detail as detail
    from app.modules.ads.contract.tree import ad_figures

    campaign = _detail(db, user, campaign_id)
    selectors.with_controls(db, owner=user, campaign=campaign)
    selectors.with_tree_badge(campaign=campaign)
    campaign.settings = selectors.row_settings(campaign=campaign)
    return detail(
        db,
        owner=user,
        campaign=campaign,
        groups=_groups(db, user, campaign),
        history=selectors.campaign_history(db, owner=user, campaign=campaign),
        chips=ad_figures(db, owner=user, campaign=campaign),
    )


def _tree(db: Session, user: User, campaign_id: uuid.UUID) -> dict[str, Any]:
    from app.modules.ads.contract.tree import ad_figures, campaign_tree

    campaign = _detail(db, user, campaign_id)
    selectors.with_controls(db, owner=user, campaign=campaign)
    return campaign_tree(
        _groups(db, user, campaign),
        chips=ad_figures(db, owner=user, campaign=campaign),
    )


@router.get("/{campaign_id}/tree", response_model=CampaignTree)
def campaign_tree(campaign_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Groups and adverts under one row, with their last week's figures."""
    return _tree(db, user, campaign_id)


@router.get("/{campaign_id}/ads", response_model=list[CampaignAd])
def campaign_ads(
    campaign_id: uuid.UUID, db: Db, user: CurrentUser
) -> list[dict[str, Any]]:
    """Every advert of one campaign, numbered across its groups."""
    tree = _tree(db, user, campaign_id)
    return [ad for group in tree["groups"] for ad in group["ads"]]


@router.get("/{campaign_id}/history", responses={200: {"model": CampaignHistoryOut}})
def campaign_history(
    campaign_id: uuid.UUID, db: Db, user: CurrentUser
) -> dict[str, Any]:
    campaign = _detail(db, user, campaign_id)
    rows = selectors.campaign_history(db, owner=user, campaign=campaign)
    undoable = actions.revertible(db, [row.log for row in rows])
    return {
        "history": [
            {
                "log": _action(row.log, revertible=row.log.id in undoable),
                "level_label": row.level_label,
                "amount": row.amount,
                "moment": row.moment,
                "reason": row.log.reason,
            }
            for row in rows
        ]
    }


@router.get("/actions/{action_id}", responses={200: {"model": ActionStateOut}})
def action_state_by_id(
    action_id: uuid.UUID, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """One change, followed by its id: from the chat, a proposal or the centre."""
    from app.modules.audit.models import ActionLog

    row = db.scalar(
        select(ActionLog).where(
            ActionLog.owner_id == user.id, ActionLog.id == action_id
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="O'zgarish topilmadi.")
    target = selectors.managed_target(
        db, owner=user, level=row.target_level, external_id=row.target_external_id
    )
    failure = (
        _failure(db, action=row, target=target, level=row.target_level)
        if target is not None
        else None
    )
    return {
        **(_action(row, revertible=row.id in actions.revertible(db, [row])) or {}),
        "target": {
            "level": row.target_level,
            "external_id": row.target_external_id,
            "name": str(getattr(target, "name", "") or ""),
            "provider": row.target_provider,
        },
        "polling": selectors.still_running([row]),
        "explanation_html": failure.explanation_html if failure is not None else "",
        "explaining": failure.explaining if failure is not None else False,
    }


@router.post("/{campaign_id}/delete", responses={200: {"model": MessageOut}})
def campaign_delete(
    campaign_id: uuid.UUID, db: Db, user: CurrentUser
) -> dict[str, Any]:
    campaign = _detail(db, user, campaign_id)
    actions.request(
        db,
        user=user,
        ask=actions.Delete(
            level=ManagedLevel.CAMPAIGN, external_id=campaign.external_id
        ),
    )
    db.commit()
    return {"message": "Kampaniyani o'chirish so'rovi yuborildi."}


# -- the switches ----------------------------------------------------------------------------


def _target(db: Session, user: User, level: str, external_id: str) -> Any:
    if level not in ManagedLevel.values:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    found = selectors.shown_target(db, owner=user, level=level, external_id=external_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Bu reklama topilmadi.")
    return found


def _campaign_of(target: Any) -> Any:
    found = target
    for step in ("adset", "campaign"):
        found = getattr(found, step, found)
    return found


def control_state(
    db: Session,
    user: User,
    *,
    level: str,
    external_id: str,
    tries: int = 0,
    refusal: str = "",
) -> dict[str, Any]:
    """What became of the last press on one object, as its status line draws it.

    Pending while a change on it, or on a row above or below it that it
    moves, is still on its way.
    """
    target = _target(db, user, level, external_id)
    beside = selectors.clusters_beside(db, owner=user, target=target, level=level)
    latest = selectors.latest_actions(
        db,
        owner=user,
        external_ids=[external_id, *(obj.external_id for _at, obj in beside)],
    )
    pending = any(row.status == ActionStatus.PENDING for row in latest.values())
    action = latest.get(external_id)
    note = _failure(db, action=action, target=target, level=level)
    return {
        "level": level,
        "external_id": external_id,
        "pending": pending and tries < MAX_ACTION_POLLS,
        "stalled": pending and tries >= MAX_ACTION_POLLS,
        "failure": {
            "text": " ".join(
                part for part in (note.sentence, note.provider_words) if part
            ),
            "fix": {"label": note.fix_label, "url": note.fix_url}
            if note.fix_label and note.fix_url
            else None,
            "explanation_html": note.explanation_html or None,
            "explaining": note.explaining or None,
        }
        if note is not None
        else None,
        "action": {
            "id": str(action.id),
            "status": action.status,
            "dry_run": action.dry_run,
            "revertible": actions.undoing(action) is not None,
        }
        if action is not None
        else None,
        "tries": tries + 1,
        "poll_seconds": ACTION_POLL_SECONDS,
        "refused": refusal or None,
    }


def _failure(db: Session, *, action: Any, target: Any, level: str) -> Any:
    """Why the latest change failed, with the written answer when there is one."""
    from app.common.i18n import get_language
    from app.modules.ads.selectors.actions import account_of
    from app.modules.ads.selectors.failures import explained, failure_note
    from app.modules.chat.services.explain import explain_later

    if action is None or action.status != ActionStatus.FAILED:
        return None
    note = explained(
        db,
        note=failure_note(action=action, target=target, level=level),
        action=action,
        account_external_id=account_of(target=target, level=level).external_id,
        language=get_language(),
    )
    if note.explaining:
        explain_later(log=action, language=get_language())
    return note


def _changed(
    db: Session,
    user: User,
    level: str,
    external_id: str,
    run: Any,
    *,
    field: str = "",
    strict: bool = False,
) -> dict[str, Any]:
    """Send the change and answer its state. ``strict``: a refusal is a 409, the
    sentence under ``field``; otherwise it rides in the state as ``refused``."""
    try:
        refusal = run() or ""
        db.commit()
    except DomainError as exc:
        db.rollback()
        refusal = exc.message
    if refusal and strict:
        raise PressRefused(refusal, field=field)
    return control_state(
        db, user, level=level, external_id=external_id, refusal=refusal
    )


@router.get("/manage/{level}/{external_id}/state", response_model=ControlState)
def action_state(
    level: str, external_id: str, db: Db, user: CurrentUser, tries: int = TRIES_Q
) -> dict[str, Any]:
    return control_state(db, user, level=level, external_id=external_id, tries=tries)


@router.post("/manage/{level}/{external_id}/pause", response_model=ControlState)
def pause(level: str, external_id: str, db: Db, user: CurrentUser) -> dict[str, Any]:
    _target(db, user, level, external_id)
    return _changed(
        db,
        user,
        level,
        external_id,
        lambda: (
            actions.request(
                db,
                user=user,
                ask=actions.Pause(level=level, external_id=external_id),
            )
            and ""
        ),
    )


@router.post("/manage/{level}/{external_id}/resume", response_model=ControlState)
def resume(level: str, external_id: str, db: Db, user: CurrentUser) -> dict[str, Any]:
    target = _target(db, user, level, external_id)

    def run() -> str:
        chain = (
            selectors.campaign_chain(db, owner=user, campaign=target)
            if level == ManagedLevel.CAMPAIGN
            else selectors.delivery_chain(target=target, level=level)
        )
        return " ".join(services.start_delivery(db, user=user, targets=chain).refused)

    return _changed(db, user, level, external_id, run)


@router.get(
    "/manage/{level}/{external_id}/budget", responses={200: {"model": BudgetFormOut}}
)
def budget_form(
    level: str, external_id: str, db: Db, user: CurrentUser
) -> dict[str, Any]:
    target = _target(db, user, level, external_id)
    controls = selectors.controls_for(target=target, level=level)
    places = provider_money(provider=controls.provider).decimal_places(
        controls.currency
    )
    current = controls.daily_budget_minor
    return {
        "currency": controls.currency,
        "places": places,
        "floor_minor": controls.floor_minor,
        "floor": format_minor(
            amount_minor=controls.floor_minor or None,
            currency=controls.currency,
            places=places,
        ),
        "current_minor": current,
        "current": str(Decimal(current).scaleb(-places))
        if current is not None
        else None,
        "early_hours": selectors.hours_to_wait(
            db,
            owner=user,
            level=level,
            external_id=str(target.external_id),
            now=utcnow(),
        ),
    }


class BudgetIn(Camel):
    daily_budget: Decimal = Field(
        gt=0, description="In the currency's main unit, e.g. 12.50"
    )


@router.post("/manage/{level}/{external_id}/budget", response_model=ControlState)
def budget(
    level: str, external_id: str, body: BudgetIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    from app.modules.ads.inputs import Problems
    from app.modules.ads.inputs.budget import budget_minor

    target = _target(db, user, level, external_id)
    controls = selectors.controls_for(target=target, level=level)
    problems = Problems()
    asked = budget_minor(
        body.daily_budget,
        currency=controls.currency,
        money=provider_money(provider=controls.provider),
        floor_minor=controls.floor_minor,
        problems=problems,
    )
    try:
        problems.refuse()
    except InputRefused as exc:
        raise InputRefused(
            {to_camel(key): words for key, words in exc.problems.items()}
        ) from None
    return _changed(
        db,
        user,
        level,
        external_id,
        lambda: (
            actions.request(
                db,
                user=user,
                ask=actions.Budget(
                    level=level, external_id=external_id, daily_budget_minor=asked
                ),
            )
            and ""
        ),
        field="dailyBudget",
        strict=True,
    )


class RevertIn(BaseModel):
    log: str


@router.post("/manage/{level}/{external_id}/revert", response_model=ControlState)
def revert(
    level: str, external_id: str, body: RevertIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    _target(db, user, level, external_id)

    def run() -> str:
        try:
            actions.revert(db, user=user, log_id=body.log)
        except DomainError:
            raise NothingToRevert from None
        return ""

    return _changed(db, user, level, external_id, run, strict=True)


def _switch_campaign(
    db: Session, user: User, campaign_id: uuid.UUID, wanted: str
) -> dict[str, Any]:
    """The list and the campaign page switch a campaign by this product's id."""
    campaign = _detail(db, user, campaign_id)
    pressed = pause if wanted == "pause" else resume
    state = pressed(ManagedLevel.CAMPAIGN, campaign.external_id, db, user)
    if state["refused"]:
        raise PressRefused(state["refused"])
    return state


@router.post("/{campaign_id}/pause", response_model=ControlState)
def campaign_pause(campaign_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    return _switch_campaign(db, user, campaign_id, "pause")


@router.post("/{campaign_id}/resume", response_model=ControlState)
def campaign_resume(
    campaign_id: uuid.UUID, db: Db, user: CurrentUser
) -> dict[str, Any]:
    return _switch_campaign(db, user, campaign_id, "resume")


@router.post(
    "/manage/adset/{external_id}/delete", responses={200: {"model": DeletedOut}}
)
def adset_delete(external_id: str, db: Db, user: CurrentUser) -> dict[str, Any]:
    adset = _target(db, user, ManagedLevel.ADSET, external_id)
    actions.request(
        db,
        user=user,
        ask=actions.Delete(level=ManagedLevel.ADSET, external_id=external_id),
    )
    db.commit()
    return {
        "message": "Guruhni o'chirish so'rovi yuborildi.",
        "campaign_id": str(adset.campaign.id),
    }


@router.post("/manage/ad/{external_id}/delete", responses={200: {"model": DeletedOut}})
def ad_delete(external_id: str, db: Db, user: CurrentUser) -> dict[str, Any]:
    ad = _target(db, user, ManagedLevel.AD, external_id)
    actions.request(
        db,
        user=user,
        ask=actions.Delete(level=ManagedLevel.AD, external_id=external_id),
    )
    db.commit()
    return {
        "message": "Reklamani o'chirish so'rovi yuborildi.",
        "campaign_id": str(ad.adset.campaign.id),
    }


from app.modules.ads.routers import editing as _editing  # noqa: E402, F401
