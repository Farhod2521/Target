"""The agent's screens over HTTP.

``GET /agent`` is the waiting list: open proposals, the watch lines under
groups launched here, the open frequency levels and today's groups burning
money - each read from the database, never from the provider. A press
(approve, a watch move, a frequency answer) is queued and answers at once;
while ``working`` holds, poll ``GET /agent`` every ``poll_seconds``.

``/agent/history`` is what was answered and what came of it, page by page;
``/agent/settings`` turns the agent on and off and says how hard it presses.
"""

import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.common.exceptions import DomainError, NotFound
from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.models import Ad
from app.modules.ads.selectors.actions import account_of, campaigns_for, managed_target
from app.modules.ads.selectors.creatives import creative_of
from app.modules.ads.selectors.media import asset_row, media_library
from app.modules.ads.selectors.pages import current_page_scope, page_advertising
from app.modules.agent.advert_words import AdvertWords
from app.modules.agent.constants import (
    HISTORY_PAGE,
    IN_FLIGHT_POLL_SECONDS,
    OPEN_STATUSES,
    SuggestionKind,
)
from app.modules.agent.frequency_copy import (
    ADD_CREATIVE,
    WORKING_WELL,
    frequency_body,
    frequency_title,
)
from app.modules.agent.models import AgentSuggestion, FrequencyAlert
from app.modules.agent.selectors.cards import history_cards
from app.modules.agent.selectors.frequency import alerts_to_show, creative_target
from app.modules.agent.selectors.launch_watch import watched_groups
from app.modules.agent.selectors.policy import policy_for
from app.modules.agent.selectors.runs import recent
from app.modules.agent.selectors.same_day import burning_groups
from app.modules.agent.selectors.suggestions import one
from app.modules.agent.selectors.summary import proposals
from app.modules.agent.selectors.verdicts import campaign_verdicts
from app.modules.agent.services import (
    act_on_watch,
    answer_working_well,
    approve_suggestion,
    reject_suggestion,
    save_policy,
)

router = APIRouter(prefix="/agent", tags=["agent"])

HEADLINE_LIMIT = 255
MESSAGE_LIMIT = 2000
POLICY_LIMITS: dict[str, tuple[int, int]] = {
    "window_days": (3, 30),
    "cooldown_hours": (12, 168),
    "max_per_run": (1, 10),
    "budget_step_pct": (5, 50),
}
SENT = {
    "delete": "O'chirish so'rovi yuborildi. Yangi reklamani «Reklama yaratish» "
    "bo'limida qaytadan yaratishingiz mumkin.",
    "pause": "To'xtatish so'rovi yuborildi.",
    "resume": "Qayta yoqish so'rovi yuborildi.",
}


class ApproveIn(BaseModel):
    shown_words: bool = Field(
        False, description="The card showed a new advert's proposed words."
    )


class NewAdIn(BaseModel):
    message: str = Field("", max_length=MESSAGE_LIMIT)
    headline: str = Field("", max_length=HEADLINE_LIMIT)
    description: str = Field("", max_length=HEADLINE_LIMIT)
    asset_id: str = Field("", description="A library row id; empty keeps the picture.")


class PolicyIn(BaseModel):
    is_enabled: bool
    self_repair: bool = False
    window_days: int
    cooldown_hours: int
    max_per_run: int
    budget_step_pct: int


# -- the waiting list -----------------------------------------------------------------


def _watch_line(row: Any) -> dict[str, Any]:
    return {
        **asdict(row),
        "watch": asdict(row.watch),
        "running": asdict(row.running) if row.running is not None else None,
    }


def _alert(row: FrequencyAlert) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "adset_external_id": row.adset_external_id,
        "level": row.level,
        "frequency": row.frequency,
        "title": frequency_title(row),
        "body": frequency_body(row),
        "answer": row.answer,
        "created_at": row.created_at,
        "buttons": {"fine": WORKING_WELL, "creative": ADD_CREATIVE},
    }


def _waiting(db: Session, *, user: User, now: datetime) -> dict[str, Any]:
    from app.modules.integrations.selectors.slots import enabled_ad_accounts

    open_ones = proposals(db, owner=user, now=now)
    scope = current_page_scope(db, owner=user)
    hidden = scope.outside
    accounts = enabled_ad_accounts(db, owner=user)
    return jsonable_encoder(
        {
            "cards": open_ones.cards,
            "policy": _policy(open_ones.policy),
            "counted": open_ones.counted,
            "late": open_ones.late,
            "working": open_ones.working,
            "poll_seconds": IN_FLIGHT_POLL_SECONDS,
            "watch": [
                _watch_line(row)
                for row in watched_groups(
                    db, owner=user, accounts=accounts, now=now, hidden_adsets=hidden
                )
            ],
            "frequency": [
                _alert(row)
                for row in alerts_to_show(db, owner=user, now=now, hidden_adsets=hidden)
            ],
            "burning": [
                asdict(row)
                for account in accounts
                for row in burning_groups(
                    db, owner=user, account=account, now=now, hidden_adsets=hidden
                )
            ],
        }
    )


def _policy(row: Any) -> dict[str, Any] | None:
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


@router.get("")
def waiting(db: Db, user: CurrentUser) -> dict[str, Any]:
    """What the agent is waiting on an answer for, and what it is watching."""
    return _waiting(db, user=user, now=utcnow())


@router.get("/history")
def history(
    db: Db,
    user: CurrentUser,
    before: datetime | None = Query(None, description="The last card's decided_at."),
) -> dict[str, Any]:
    """What was answered, what came of it, and which nights were quiet."""
    scope = current_page_scope(db, owner=user)
    found = history_cards(
        db, owner=user, limit=HISTORY_PAGE + 1, before=before, scope=scope
    )
    return jsonable_encoder(
        {
            "history": found[:HISTORY_PAGE],
            "more": len(found) > HISTORY_PAGE,
            "runs": recent(db, owner=user) if before is None else [],
        }
    )


def _suggestion(db: Session, *, user: User, pk: uuid.UUID) -> AgentSuggestion:
    found = one(db, owner=user, pk=pk)
    if found is None:
        raise NotFound("Bu taklif topilmadi.")
    return found


def _shown_words(suggestion: AgentSuggestion, *, shown: bool) -> AdvertWords | None:
    """The proposed words of a new advert, when the card that was pressed showed them."""
    if suggestion.kind != SuggestionKind.NEW_AD or not shown:
        return None
    payload = suggestion.payload or {}
    if not str(payload.get("message", "")).strip():
        return None
    return AdvertWords(
        message=str(payload.get("message", "")),
        headline=str(payload.get("headline", "")),
        description=str(payload.get("description", "")),
    )


def _answered(db: Session, user: User, text: str) -> dict[str, Any]:
    return _waiting(db, user=user, now=utcnow()) | {"detail": text}


@router.post("/{suggestion_id}/approve")
def approve(
    suggestion_id: uuid.UUID, body: ApproveIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """Say yes: the change is queued and carried out by the worker."""
    suggestion = _suggestion(db, user=user, pk=suggestion_id)
    try:
        approve_suggestion(
            db,
            user=user,
            suggestion=suggestion,
            words=_shown_words(suggestion, shown=body.shown_words),
        )
    except DomainError:
        db.rollback()
        raise
    db.commit()
    return _answered(db, user, "Bajarilmoqda.")


@router.post("/{suggestion_id}/reject")
def reject(suggestion_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Say no. Nothing reaches the provider."""
    suggestion = _suggestion(db, user=user, pk=suggestion_id)
    reject_suggestion(db, user=user, suggestion=suggestion)
    db.commit()
    return _answered(db, user, "Taklif rad etildi.")


def _new_ad(
    db: Session, *, user: User, pk: uuid.UUID
) -> tuple[AgentSuggestion, Ad | None]:
    suggestion = _suggestion(db, user=user, pk=pk)
    if (
        suggestion.kind != SuggestionKind.NEW_AD
        or suggestion.status not in OPEN_STATUSES
    ):
        raise NotFound("Bu taklif topilmadi.")
    found = managed_target(
        db, owner=user, level=ManagedLevel.AD, external_id=suggestion.target_external_id
    )
    return suggestion, found if isinstance(found, Ad) else None


@router.get("/{suggestion_id}/new-ad")
def new_ad(suggestion_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """A new advert the agent proposes, read before anything is sent."""
    from app.modules.ads.services.swap import SWAPPABLE_KINDS

    suggestion, ad = _new_ad(db, user=user, pk=suggestion_id)
    content = creative_of(db, owner=user, ad=ad) if ad is not None else None
    library = (
        media_library(
            db,
            owner=user,
            provider=ad.provider,
            ad_account=account_of(target=ad, level=ManagedLevel.AD),
            kinds=SWAPPABLE_KINDS,
        )
        if ad is not None
        else []
    )
    payload = suggestion.payload or {}
    return jsonable_encoder(
        {
            "suggestion_id": str(suggestion.id),
            "ad": {"external_id": ad.external_id, "name": ad.name} if ad else None,
            "current": {
                "message": content.message,
                "headline": content.headline,
                "description": content.description,
            }
            if content is not None
            else None,
            "proposed": {
                key: str(payload.get(key, ""))
                for key in ("message", "headline", "description")
            },
            "can_swap": bool(getattr(content, "story_raw", None)),
            "library": [asset_row(row) for row in library],
            "limits": {"headline": HEADLINE_LIMIT, "message": MESSAGE_LIMIT},
        }
    )


@router.post("/{suggestion_id}/new-ad")
def save_new_ad(
    suggestion_id: uuid.UUID, body: NewAdIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """The yes: the words as edited, carried out as the proposal's approval."""
    from app.common.exceptions import InputRefused

    suggestion, ad = _new_ad(db, user=user, pk=suggestion_id)
    if ad is None:
        raise NotFound("Reklama topilmadi.")
    if not any(
        word.strip() for word in (body.message, body.headline, body.description)
    ):
        raise InputRefused(
            {"message": "Reklama hech bo'lmasa bitta jumla aytishi kerak."}
        )
    words = AdvertWords(
        message=body.message,
        headline=body.headline,
        description=body.description,
        asset_id=body.asset_id,
    )
    try:
        approve_suggestion(db, user=user, suggestion=suggestion, words=words)
    except DomainError:
        db.rollback()
        raise
    db.commit()
    return _answered(db, user, "Yangi reklama yuborildi. Bir necha soniyada ko'rinadi.")


# -- settings -------------------------------------------------------------------------


@router.get("/settings")
def settings_page(db: Db, user: CurrentUser) -> dict[str, Any]:
    """The agent's switches and numbers, with the range each may take."""
    return jsonable_encoder(
        {
            "policy": _policy(policy_for(db, owner=user)),
            "limits": {
                name: {"min": low, "max": high}
                for name, (low, high) in POLICY_LIMITS.items()
            },
        }
    )


@router.put("/settings")
def save_settings(body: PolicyIn, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Store the settings; numbers out of range are clamped, not refused."""
    values = body.model_dump()
    for name, (low, high) in POLICY_LIMITS.items():
        values[name] = max(low, min(high, int(values[name])))
    row = save_policy(db, user=user, **values)
    db.commit()
    return jsonable_encoder({"policy": _policy(row), "detail": "Saqlandi."})


# -- the campaign list's verdicts -----------------------------------------------------


@router.get("/verdicts")
def verdicts(db: Db, user: CurrentUser) -> dict[str, Any]:
    """Every campaign the list draws, with what the agent makes of it."""
    campaigns = list(
        campaigns_for(
            db,
            owner=user,
            external_ids=page_advertising(db, owner=user).campaign_ids,
        )
    )
    rows = campaign_verdicts(db, owner=user, campaigns=campaigns, now=utcnow())
    return jsonable_encoder({"rows": [asdict(row) for row in rows]})


# -- buttons under a watch line and a frequency level ---------------------------------


@router.post("/watch/{adset_id}/{move}")
def watch_act(adset_id: str, move: str, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Carry out one advised move on a group, if it is still advised."""
    try:
        act_on_watch(db, user=user, adset_id=adset_id, move=move, now=utcnow())
    except DomainError:
        db.rollback()
        raise
    db.commit()
    return _answered(
        db, user, SENT.get(move, "Byudjetni o'zgartirish so'rovi yuborildi.")
    )


@router.post("/frequency/{alert_id}/fine")
def frequency_fine(alert_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """«Reklama yaxshi ishlayapti»."""
    answer_working_well(db, user=user, alert_id=str(alert_id), now=utcnow())
    db.commit()
    return _answered(db, user, "Javobingiz saqlandi.")


@router.get("/frequency/{alert_id}/creative")
def frequency_creative(
    alert_id: uuid.UUID, db: Db, user: CurrentUser
) -> dict[str, str]:
    """«Qo'shimcha kreativ qo'shamiz»: the advert to add a creative beside.

    The client opens the advert's edit screen,
    ``/api/v1/campaigns/manage/ad/{external_id}/edit``.
    """
    row = db.scalar(
        select(FrequencyAlert).where(
            FrequencyAlert.owner_id == user.id, FrequencyAlert.id == alert_id
        )
    )
    advert = (
        creative_target(db, owner=user, adset_id=row.adset_external_id)
        if row is not None
        else ""
    )
    if not advert:
        raise NotFound("Bu guruhda ishlab turgan reklama topilmadi.")
    return {
        "ad_external_id": advert,
        "edit_url": f"/api/v1/campaigns/manage/ad/{advert}/edit",
    }
