"""Opening a preparation, answering its questions, handing it to the worker,
and throwing it away or clearing what a failed one left behind."""

import logging
from datetime import date
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common import storage
from app.common.db import on_commit, utcnow
from app.common.presets import offered_goals
from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import (
    ATTRIBUTION,
    BUDGET_LEVEL,
    BUDGET_SHARING,
    CALL_TO_ACTION,
    CAMPAIGN_TYPE,
    CHAT_QUESTIONS,
    CHAT_QUESTIONS_READING,
    CONVERSION_EVENT,
    FORM_DEPTH,
    FREE_PROPOSALS,
    FREQUENCY_CAP,
    HIGHER_INTENT,
    LAUNCH_PROGRESS,
    LAUNCH_RELATED_TYPE,
    LEAD_FORM_CHOICE,
    LEAD_FORM_NAME,
    LEAD_FORM_QUESTIONS,
    PIXEL_ID,
    URL_TAGS,
    LaunchStatus,
    LaunchStep,
)
from app.modules.ads.draft import empty_draft, is_written
from app.modules.ads.exceptions import (
    AnswersIncomplete,
    FreeProposalsUsed,
    LaunchNotDiscardable,
    NoAdAccount,
    NoPage,
    NothingToCleanUp,
    PreparationRunning,
    ProfileIncomplete,
)
from app.modules.ads.models import CampaignLaunch, LaunchCreative
from app.modules.ads.rows import fresh
from app.modules.ads.selectors.launches import (
    answers_complete,
    open_launch,
    provider_for,
    stranded_refs,
)
from app.modules.ads.selectors.quality import proposals_written
from app.modules.ads.trace import LaunchTrace
from app.modules.audit.constants import EventName

logger = logging.getLogger(__name__)
INITIAL_PROGRESS: Final = 5
LIVE_STATUSES = (LaunchStatus.CREATING, LaunchStatus.CREATED)
CLEANUP_KEY: Final = "cleanup"
CLEANUP_PENDING: Final = "pending"
CLEANUP_REFUSED: Final = "refused"
ANSWER_KEYS = frozenset(
    {
        "goal",
        "offer_text",
        "text_mode",
        "shared_text",
        "daily_budget_minor",
        "max_result_cost_minor",
        "link_url",
        "welcome_text",
        "chat_channel",
        "phone_number",
        "start_date",
        "end_date",
        "total_cap_minor",
        LEAD_FORM_CHOICE,
        LEAD_FORM_QUESTIONS,
        LEAD_FORM_NAME,
        "goal_text",
        "goal_reading",
        CHAT_QUESTIONS,
        CHAT_QUESTIONS_READING,
        CAMPAIGN_TYPE,
        CONVERSION_EVENT,
        PIXEL_ID,
        URL_TAGS,
        CALL_TO_ACTION,
        ATTRIBUTION,
        FREQUENCY_CAP,
        HIGHER_INTENT,
        FORM_DEPTH,
        BUDGET_LEVEL,
        BUDGET_SHARING,
    }
)
INVALIDATING = frozenset({"goal", "offer_text", "goal_text"})


# -- the gate --------------------------------------------------------------------------


def check_preparation_allowance(db: Session, *, owner: User) -> None:
    """Refuse a new proposal this account may not have."""
    from app.modules.billing.selectors.subscription import has_live_subscription
    from app.modules.billing.services import require_preparation

    require_preparation(db, owner=owner)
    if has_live_subscription(db, owner=owner):
        return
    if proposals_written(db, owner=owner) >= FREE_PROPOSALS:
        raise FreeProposalsUsed(limit=FREE_PROPOSALS)


def start_launch(db: Session, *, user: User) -> CampaignLaunch:
    """The launch the wizard is about to walk through. Caller commits."""
    from app.modules.ads.services.manage import check_campaign_allowance
    from app.modules.billing.services import (
        require_preparation,
        require_setup_completed,
    )
    from app.modules.businesses.selectors import business_for_page
    from app.modules.integrations.selectors import (
        active_ad_account,
        active_page,
        page_ad_account,
    )

    require_preparation(db, owner=user)
    page = active_page(db, owner=user)
    check_campaign_allowance(db, owner=user)
    business = business_for_page(db, owner=user, page=page)
    if business is None or not business.category:
        raise ProfileIncomplete
    provider = provider_for(db, owner=user)
    if not offered_goals(provider=provider, category=business.category):
        raise ProfileIncomplete
    account = (
        page_ad_account(db, owner=user, page=page)
        if page is not None
        else active_ad_account(db, owner=user)
    )
    existing = open_launch(db, owner=user, page=page, ad_account=account)
    if existing is not None:
        return existing
    check_preparation_allowance(db, owner=user)
    if account is None:
        raise NoAdAccount
    if page is None:
        raise NoPage
    require_setup_completed(db, owner=user)
    launch = CampaignLaunch(
        owner_id=user.id,
        provider=provider,
        ad_account_id=account.id,
        page_id=page.id,
        currency=account.currency,
        answers={},
        draft={},
    )
    db.add(launch)
    db.flush()
    return launch


def request_preparation(db: Session, *, launch: CampaignLaunch) -> None:
    """Mark the launch as being worked on and queue the work. Caller commits."""
    from app.modules.ads.tasks import build_draft_task

    check_preparation_allowance(db, owner=launch.owner)
    if launch.status == LaunchStatus.BUILDING:
        raise PreparationRunning
    if not answers_complete(launch=launch):
        raise AnswersIncomplete
    started = utcnow()
    fields: dict[str, Any] = {
        "status": str(LaunchStatus.BUILDING),
        "step": str(LaunchStep.ANSWERS),
        "progress": INITIAL_PROGRESS,
        "started_at": started,
        "finished_at": None,
        "error_code": "",
        "error_message": "",
        "updated_at": started,
    }
    claimed = db.execute(
        update(CampaignLaunch)
        .where(
            CampaignLaunch.owner_id == launch.owner_id,
            CampaignLaunch.id == launch.id,
            CampaignLaunch.status != str(LaunchStatus.BUILDING),
        )
        .values(**fields)
        .execution_options(synchronize_session=False)
    ).rowcount
    if not claimed:
        raise PreparationRunning
    for name, value in fields.items():
        setattr(launch, name, value)
    run = started.isoformat()
    launch_id = str(launch.id)
    on_commit(db, lambda: build_draft_task.delay(launch_id, run))


# -- the answers -----------------------------------------------------------------------


def same_wording(before: object, after: object) -> bool:
    return str(before or "").split() == str(after or "").split()


def save_answers(
    db: Session, *, launch: CampaignLaunch, **values: object
) -> CampaignLaunch:
    """Merge answers into the launch, one screen's worth at a time."""
    unknown = set(values) - ANSWER_KEYS
    if unknown:
        raise ValueError(f"not a wizard answer: {sorted(unknown)}")
    given = {key: value for key, value in values.items() if value is not None}
    if not given:
        return launch
    answers = fresh(launch, "answers")
    contradicted = {
        key
        for key in INVALIDATING & given.keys()
        if not same_wording(answers.get(key), given[key])
    }
    if "goal" in given and str(answers.get("goal") or "") != str(given["goal"]):
        answers.pop(CAMPAIGN_TYPE, None)
    answers.update(given)
    if contradicted and is_written(launch.draft):
        launch.draft = empty_draft()
        launch.targeting = {}
        launch.status = str(LaunchStatus.DRAFT)
        launch.step = ""
        launch.progress = 0
    if "daily_budget_minor" in given:
        launch.daily_budget_minor = int(given["daily_budget_minor"])  # type: ignore[call-overload]
    if "max_result_cost_minor" in given:
        amount = int(given["max_result_cost_minor"])  # type: ignore[call-overload]
        launch.max_result_cost_minor = amount or None
    if "start_date" in given:
        launch.start_date = date.fromisoformat(str(given["start_date"]))
    if "total_cap_minor" in given:
        amount = int(given["total_cap_minor"] or 0)  # type: ignore[call-overload]
        launch.total_cap_minor = amount or None
    if "end_date" in given:
        named = str(given["end_date"] or "")
        launch.end_date = date.fromisoformat(named) if named else None
    db.flush()
    return launch


# -- the progress of a creation -------------------------------------------------------


def starting(
    db: Session, launch: CampaignLaunch, *, step: str, watch: LaunchTrace | None = None
) -> None:
    """Say which call is about to be made, before making it."""
    if launch.step == step:
        return
    was = launch.step
    launch.step = step
    db.commit()
    if watch is not None:
        watch.db("CampaignLaunch", {"step": (was, launch.step)})


def advance(
    db: Session,
    launch: CampaignLaunch,
    *,
    step: str,
    ref: Any | None = None,
    dropped: dict[str, object] | None = None,
    watch: LaunchTrace | None = None,
) -> None:
    """Record one finished step, ref and all, before the next one starts."""
    was = (launch.step, launch.progress, dict(launch.created_refs or {}))
    if ref is not None:
        refs = fresh(launch, "created_refs")
        ref_field.put(refs, step, ref.id)
    if dropped:
        launch.dropped = dict(dropped)
    launch.step = step
    launch.progress = max(launch.progress, LAUNCH_PROGRESS[step])
    db.commit()
    if watch is not None:
        watch.db(
            "CampaignLaunch",
            {
                "step": (was[0], launch.step),
                "progress": (was[1], launch.progress),
                "created_refs": (was[2], dict(launch.created_refs or {})),
            },
        )


# -- throwing it away ------------------------------------------------------------------


def is_discardable(db: Session, *, launch: CampaignLaunch) -> bool:
    return not stranded_refs(db, launch) and launch.status not in LIVE_STATUSES


def discard_launch(db: Session, *, launch: CampaignLaunch) -> None:
    """Delete the preparation and the files it was carrying. Commits."""
    from app.modules.audit.services import emit

    if not is_discardable(db, launch=launch):
        raise LaunchNotDiscardable
    emit(
        db,
        owner_id=launch.owner_id,
        name=EventName.LAUNCH_DISCARDED,
        aggregate_type=LAUNCH_RELATED_TYPE,
        aggregate_id=launch.id,
        payload={"status": launch.status, "provider": launch.provider},
    )
    rows = list(
        db.scalars(select(LaunchCreative).where(LaunchCreative.launch_id == launch.id))
    )
    uploads = [row.media_upload for row in rows if row.media_upload]
    for row in rows:
        db.delete(row)
    db.delete(launch)
    on_commit(db, lambda: _remove_all(uploads))
    db.commit()


def _remove_all(uploads: list[str]) -> None:
    for name in uploads:
        try:
            storage.delete(name)
        except OSError:
            logger.exception("discarded_upload_not_removed", extra={"file": name})


def request_cleanup(db: Session, *, launch: CampaignLaunch) -> None:
    """Queue the rollback. Raises when there is nothing to remove. Commits."""
    from app.modules.ads.tasks import clean_up_launch_task
    from app.modules.audit.services import emit

    if launch.status != LaunchStatus.FAILED or not stranded_refs(db, launch):
        raise NothingToCleanUp
    if (launch.error_detail or {}).get(CLEANUP_KEY) == CLEANUP_PENDING:
        return
    detail = fresh(launch, "error_detail")
    detail[CLEANUP_KEY] = CLEANUP_PENDING
    emit(
        db,
        owner_id=launch.owner_id,
        name=EventName.LAUNCH_CLEANUP_REQUESTED,
        aggregate_type=LAUNCH_RELATED_TYPE,
        aggregate_id=launch.id,
        payload={"remaining": sorted(launch.created_refs or {})},
    )
    launch_id = str(launch.id)
    on_commit(db, lambda: clean_up_launch_task.delay(launch_id))
    db.commit()


def clean_up_launch(db: Session, *, launch_id: str) -> str:
    """Worker half: run the rollback, then write down how it went."""
    from app.modules.ads.services.rollback import rollback_stranded_launch

    outcome = rollback_stranded_launch(db, launch_id=launch_id)
    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if launch is None:
        return outcome
    db.refresh(launch)
    detail = fresh(launch, "error_detail")
    if stranded_refs(db, launch):
        detail[CLEANUP_KEY] = CLEANUP_REFUSED
    else:
        detail.pop(CLEANUP_KEY, None)
    db.commit()
    return outcome
