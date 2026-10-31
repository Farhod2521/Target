"""The review screen: where the launch stands, and what may be done next.

The proposal itself - audience, interests, adverts, form, the advanced tab -
is :mod:`app.modules.ads.selectors.review_proposal`. This half is what the
progress poll needs too, so it stays cheap when no proposal is drawn.
"""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.common.money import format_minor, provider_money
from app.modules.ads import draft as draft_field
from app.modules.ads import geo as geo_field
from app.modules.ads.constants import (
    ACCOUNT_FAILURES,
    CREATION_STEPS,
    META_SIDE_FAILURES,
    NARROW_AUDIENCE,
    PAYMENT_FAILURES,
    POSTS_NOT_PROMOTED,
    PREPARATION_NEEDS_FIXING,
    STARTABLE,
    DraftSection,
    LaunchStatus,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.attempts import cap_not_sent, reaches_nobody
from app.modules.ads.selectors.goals import goal_optimization
from app.modules.ads.selectors.launched import (
    launch_is_mirrored,
    launched_ad_id,
    still_starting,
)
from app.modules.ads.selectors.launches import (
    ads_manager_url,
    answers_complete,
    identity_hold,
    launch_billing_url,
    launch_blocker,
    page_terms_url,
    stranded_refs,
)
from app.modules.ads.selectors.preparing import creating_stages, preparing
from app.modules.ads.selectors.proposal_changes import proposal_changes
from core.targeting.budget import daily_floor

CARD_STATUSES = (LaunchStatus.READY, LaunchStatus.ROLLED_BACK)
MAX_DRAFT_POLLS = 40
MAX_CREATE_POLLS = 90
CLEANUP_KEY = "cleanup"


def shows_proposal(launch: CampaignLaunch) -> bool:
    """Whether the proposal is drawn: ready, rolled back, or failed while built."""
    return launch.status in CARD_STATUSES or bool(
        launch.targeting and launch.status == LaunchStatus.FAILED
    )


def reach(launch: CampaignLaunch) -> dict[str, Any] | None:
    """The reach figure, or nothing at all."""
    if launch.audience_lower is None:
        if launch.estimated_at is None:
            return None
        return {"unknown": True, "at": launch.estimated_at}
    return {
        "lower": launch.audience_lower,
        "upper": launch.audience_upper,
        "is_narrow": launch.audience_lower < NARROW_AUDIENCE,
        "is_empty": reaches_nobody(launch=launch),
        "at": launch.estimated_at,
    }


def created_state(
    db: Session, *, launch: CampaignLaunch, now: datetime
) -> dict[str, Any]:
    """What the finished screen needs: has it arrived, and is it on."""
    if launch.status != LaunchStatus.CREATED:
        return {}
    return {
        "delivery_ready": launch_is_mirrored(db, owner=launch.owner, launch=launch),
        "created_ad_id": launched_ad_id(launch=launch),
        "delivery_started": launch.delivery_started_at is not None,
        "delivery_note": launch.delivery_note,
        "launch_note": draft_field.launch_note(launch.draft),
        "delivery_pending": still_starting(launch=launch, now=now),
    }


def review_state(
    db: Session,
    *,
    launch: CampaignLaunch,
    now: datetime,
    shown: str = "",
    tries: int = 0,
) -> dict[str, Any]:
    """Where the launch stands: building, ready, creating, created or failed."""
    stranded = bool(stranded_refs(db, launch))
    startable = launch.status in STARTABLE and not stranded and bool(launch.targeting)
    blocker = launch_blocker(db, launch=launch) if startable else ""
    audience = draft_field.chosen(launch.draft or {}, DraftSection.AUDIENCE) or {}
    geo_waiting = geo_field.waiting_names(audience)
    created = created_state(db, launch=launch, now=now)
    status = launch.status
    creating = status == LaunchStatus.CREATING
    failed_creating = status == LaunchStatus.FAILED and launch.step in CREATION_STEPS
    explanation = _explanation(db, launch=launch)
    keep_polling = (
        status in (LaunchStatus.BUILDING, LaunchStatus.CREATING)
        or explanation["explaining"]
        or bool(created.get("delivery_pending"))
        or (failed_creating and stranded)
        or (blocker == "places_missing" and bool(geo_waiting))
    )
    limit = (
        MAX_CREATE_POLLS
        if creating or created.get("delivery_pending")
        else MAX_DRAFT_POLLS
    )
    return {
        "id": str(launch.id),
        "status": status,
        "step": launch.step,
        "progress": launch.progress,
        "error_code": launch.error_code,
        "error_message": launch.error_message,
        "error_detail": dict(launch.error_detail or {}),
        "preparing": preparing(launch=launch, now=now, shown=shown)
        if status == LaunchStatus.BUILDING
        else None,
        "can_retry": launch.error_code not in PREPARATION_NEEDS_FIXING,
        "posts_not_promoted": [
            int(position) + 1
            for position in (launch.dropped or {}).get(POSTS_NOT_PROMOTED, [])
        ],
        **created,
        "creating_stages": creating_stages(
            launch=launch, delivering=bool(created.get("delivery_pending"))
        )
        if status in (LaunchStatus.CREATING, LaunchStatus.CREATED)
        else (),
        "failed_creating": failed_creating,
        "can_launch": startable and not blocker,
        "launch_blocker": blocker,
        "group_least": _group_least(db, launch=launch)
        if blocker == "group_budget_low"
        else "",
        "needs_fix_first": launch.error_code in META_SIDE_FAILURES,
        "show_proposal": shows_proposal(launch),
        "answers_complete": answers_complete(launch=launch),
        "proposal_changes": proposal_changes(db, launch=launch)
        if status in CARD_STATUSES
        else [],
        "has_stranded": stranded,
        "cleanup_state": (launch.error_detail or {}).get(CLEANUP_KEY, ""),
        "page_terms_url": page_terms_url(db, launch=launch)
        if launch.error_code == "page_terms"
        else "",
        "ads_manager_url": ads_manager_url(launch=launch)
        if launch.error_code in ACCOUNT_FAILURES
        else "",
        "billing_url": launch_billing_url(launch=launch)
        if launch.error_code in PAYMENT_FAILURES
        else "",
        "identity_hold": identity_hold(launch=launch)
        if launch.error_code == "account_action"
        else None,
        "cap_not_sent": cap_not_sent(db, launch=launch),
        **explanation,
        "reach": reach(launch),
        "tries": tries,
        "keep_polling": keep_polling and tries < limit,
    }


def _explanation(db: Session, *, launch: CampaignLaunch) -> dict[str, Any]:
    """The written answer under a refused launch, or that one is on its way."""
    from app.common.i18n import get_language
    from app.modules.chat.selectors.refusal import answer_language, launch_explanation

    found = launch_explanation(
        db, launch=launch, language=answer_language(get_language())
    )
    return {
        "explanation_html": found.html,
        "explaining": found.explaining,
        "refusal_key": found.key,
    }


def _group_least(db: Session, *, launch: CampaignLaunch) -> str:
    if launch.ad_account is None:
        return ""
    floor = daily_floor(
        account_minor=int(launch.ad_account.min_daily_budget_minor or 0),
        optimization_goal=goal_optimization(db, launch=launch),
    )
    places = provider_money(provider=launch.provider).decimal_places(launch.currency)
    return format_minor(amount_minor=floor, currency=launch.currency, places=places)


__all__ = [
    "CARD_STATUSES",
    "MAX_CREATE_POLLS",
    "MAX_DRAFT_POLLS",
    "created_state",
    "reach",
    "review_state",
    "shows_proposal",
]
