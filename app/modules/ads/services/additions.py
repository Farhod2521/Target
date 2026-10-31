"""Adding to what already runs: a new group in a campaign, a new advert in a group.

Both are copies. Meta holds settings the mirror does not, and an advert's link,
button and page live in its story, so the new object is built from one that
works and only what the targetologist typed differs. Both are made paused:
nothing spends until the ordinary switch is pressed.
"""

import logging
from datetime import datetime
from typing import Any

from adskit import ExternalRef
from adskit.dto import ActionResult
from adskit.errors import ProviderError
from metaads import PROVIDER
from metaads.launcher import MetaLauncher
from metaads.restage import restage, restageable
from metaads.specs import BID_LOWEST_COST, STATUS_PAUSED, AdSetSpec
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.exceptions import (
    AdditionNotOffered,
    BudgetBelowMinimum,
    CampaignFinished,
    CampaignHoldsBudget,
    CreativeNotEditable,
    GroupBudgetNeeded,
    NothingToCopy,
    UnknownTarget,
)
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.selectors import budget_floor
from app.modules.ads.services.manage import (
    ADDITION,
    Planned,
    _live,
    record,
    state_payload,
    target_for,
)
from app.modules.ads.services.mirror import _queue, _upsert
from app.modules.ads.services.swap import (
    FOREIGN_PICTURE,
    _form,
    _frame,
    _picture,
    _sweep,
    foreign_pictures,
)
from app.modules.audit.constants import ActionType
from app.modules.audit.models import ActionLog
from core.agent.guardrails import FINISHED, PAUSED

logger = logging.getLogger(__name__)


def _addable(target: Any) -> None:
    if target.provider != PROVIDER:
        raise AdditionNotOffered
    if str(target.delivery) == FINISHED:
        raise CampaignFinished


# -- a new group -----------------------------------------------------------------------


def source_group(*, campaign: Campaign, external_id: str = "") -> AdSet:
    """The group a new one is copied from: the one named, or the campaign's first."""
    groups = list(campaign.adsets)
    if not groups:
        raise NothingToCopy
    if not external_id:
        return groups[0]
    found = next((row for row in groups if row.external_id == external_id), None)
    if found is None:
        raise UnknownTarget
    return found


def plan_new_group(
    db: Session,
    *,
    user: User,
    external_id: str,
    name: str,
    source: str = "",
    daily_budget_minor: int | None = None,
) -> Planned:
    """A paused copy of one of this campaign's groups, under a new name."""
    _live(db, user)
    campaign = target_for(
        db,
        user=user,
        level=ManagedLevel.CAMPAIGN,
        external_id=external_id,
        aspect=ADDITION,
    )
    _addable(campaign)
    copied = source_group(campaign=campaign, external_id=source)
    held = campaign.daily_budget_minor is not None
    if held and daily_budget_minor:
        raise CampaignHoldsBudget
    if not held and not daily_budget_minor:
        raise GroupBudgetNeeded
    floor = budget_floor(target=copied, level=ManagedLevel.ADSET)
    if not held and floor and int(daily_budget_minor or 0) < floor:
        raise BudgetBelowMinimum(minimum_minor=floor, currency=copied.currency)
    return Planned(
        target=campaign,
        level=ManagedLevel.CAMPAIGN,
        external_id=external_id,
        action=ActionType.CREATE_ADSET,
        requested={
            "name": name,
            "source": copied.external_id,
            "daily_budget_minor": 0 if held else int(daily_budget_minor or 0),
        },
        previous=state_payload(campaign),
        dispatch=_dispatch_group,
        revertible=False,
    )


def _dispatch_group(log_id: str) -> None:
    from app.modules.ads.tasks import apply_new_group_task

    apply_new_group_task.delay(log_id)


def apply_new_group(db: Session, *, log_id: str) -> str:
    """One audit row, carried out. Returns a word for the task's log line."""
    from app.modules.ads.actions.executor import Write, carry_out

    return carry_out(
        db,
        log_id=log_id,
        kind=Write(
            actions=frozenset({ActionType.CREATE_ADSET}),
            ready=_group_ready,
            check=_not_finished,
            write=_write_group,
            finish=_finish_group,
        ),
    )


def _group_ready(_db: Session, log: ActionLog, target: Any) -> str:
    if not isinstance(target, Campaign):
        return "gone"
    source = str((log.request_payload or {}).get("source") or "")
    return "" if any(row.external_id == source for row in target.adsets) else "gone"


def _not_finished(_db: Session, job: Any) -> str:
    return "finished" if job.before.delivery == FINISHED else ""


def _account_ref(job: Any) -> ExternalRef:
    return ExternalRef(
        provider=job.log.target_provider, level="account", id=job.account.external_id
    )  # type: ignore[arg-type]


def _end_time(source: AdSet) -> str:
    """The copy's last day, unless the original's has passed."""
    ends: datetime | None = source.end_time
    return ends.isoformat() if ends is not None and ends > utcnow() else ""


def group_spec(
    *, source: AdSet, settings: dict[str, Any], campaign_id: str, asked: dict[str, Any]
) -> AdSetSpec:
    """What the new group sends: the original's delivery, under its own name and money."""
    return AdSetSpec(
        name=str(asked["name"]),
        campaign_id=campaign_id,
        daily_budget_minor=int(asked.get("daily_budget_minor") or 0),
        optimization_goal=source.optimization_goal_raw,
        billing_event=source.billing_event_raw,
        destination_type=source.destination_type_raw,
        targeting=dict(source.targeting_raw or {}),
        promoted_object=dict(source.promoted_object_raw or {}),
        end_time=_end_time(source),
        bid_strategy=str(settings.get("bid_strategy") or BID_LOWEST_COST),
        bid_amount_minor=int(settings.get("bid_amount") or 0),
        attribution=tuple(settings.get("attribution_spec") or ()),
        frequency_control=tuple(settings.get("frequency_control_specs") or ()),
        status=STATUS_PAUSED,
    )


def _write_group(_db: Session, job: Any) -> ActionResult:
    asked = job.log.request_payload
    source = source_group(campaign=job.target, external_id=str(asked["source"]))
    launcher = MetaLauncher()
    settings = (
        {}
        if job.dry_run
        else launcher.adset_settings(
            adset=ExternalRef(
                provider=job.log.target_provider,
                level=ManagedLevel.ADSET,
                id=source.external_id,
            ),  # type: ignore[arg-type]
            token=job.token,
        )
    )
    made = launcher.create_adset(
        account=_account_ref(job),
        spec=group_spec(
            source=source,
            settings=settings,
            campaign_id=job.target.external_id,
            asked=asked,
        ),
        token=job.token,
        dry_run=job.dry_run,
    )
    return ActionResult(
        ok=True,
        ref=job.ref,
        applied={"adset": made.ref.id, "name": str(asked["name"])},
        dropped=made.dropped,
        dry_run=job.dry_run,
    )


def _finish_group(db: Session, job: Any, result: ActionResult) -> None:
    asked = job.log.request_payload
    source = source_group(campaign=job.target, external_id=str(asked["source"]))
    budget = int(asked.get("daily_budget_minor") or 0)
    _upsert(
        db,
        AdSet,
        owner=job.log.owner,
        provider=job.log.target_provider,
        external_id=str(result.applied["adset"]),
        label="ad set",
        refused=[],
        defaults={
            "owner_id": job.log.owner_id,
            "campaign_id": job.target.id,
            "name": str(asked["name"]),
            "status": STATUS_PAUSED,
            "effective_status": STATUS_PAUSED,
            "delivery": PAUSED,
            "optimization_goal_raw": source.optimization_goal_raw,
            "billing_event_raw": source.billing_event_raw,
            "destination_type_raw": source.destination_type_raw,
            "daily_budget_minor": budget or None,
            "currency": source.currency,
            "targeting_raw": source.targeting_raw,
            "promoted_object_raw": source.promoted_object_raw,
            "end_time": source.end_time,
            "synced_at": utcnow(),
        },
    )
    _settled(db, job=job, result=result)


def _settled(db: Session, *, job: Any, result: ActionResult) -> None:
    record(
        db,
        log=job.log,
        target=job.target,
        result=result,
        before=job.before,
        after=None,
    )
    if not job.dry_run:
        _queue(db, job.account)


# -- a new advert ----------------------------------------------------------------------


def story_of(db: Session, *, owner: User, ad: Ad) -> dict[str, Any] | None:
    """The story a new advert can be rewritten from; none for one that runs a post."""
    from app.modules.ads.selectors import creative_of

    story = getattr(creative_of(db, owner=owner, ad=ad), "story_raw", None)
    return story if restageable(story) else None


def source_ad(db: Session, *, owner: User, group: AdSet, external_id: str = "") -> Ad:
    """The advert a new one is copied from: the one named, or the nearest that can be.

    A new group has no adverts of its own yet, so its campaign's are looked at
    too. One that can be rewritten comes first; failing that, an advert that runs
    a post, which can only be repeated as it is.
    """
    around = [
        *group.ads,
        *(
            row
            for other in group.campaign.adsets
            if other.id != group.id
            for row in other.ads
        ),
    ]
    if external_id:
        around = [row for row in around if row.external_id == external_id]
        if not around:
            raise UnknownTarget
    for row in around:
        if story_of(db, owner=owner, ad=row) is not None:
            return row
    for row in around:
        if row.creative_external_id:
            return row
    raise CreativeNotEditable


def plan_new_ad(
    db: Session,
    *,
    user: User,
    external_id: str,
    name: str,
    message: str | None = None,
    headline: str | None = None,
    description: str | None = None,
    asset_id: str = "",
    lead_form_id: str = "",
    source: str = "",
) -> Planned:
    """A paused copy of an advert in this group, with what was typed changed."""
    _live(db, user)
    group = target_for(
        db,
        user=user,
        level=ManagedLevel.ADSET,
        external_id=external_id,
        aspect=ADDITION,
    )
    _addable(group)
    copied = source_ad(db, owner=user, group=group, external_id=source)
    words = {"message": message, "headline": headline, "description": description}
    picture = _picture(db, owner=user, asset_id=asset_id)
    form = _form(db, owner=user, ad=copied, lead_form_id=lead_form_id)
    asks_a_change = (
        any(value is not None for value in words.values()) or picture or form
    )
    if asks_a_change and story_of(db, owner=user, ad=copied) is None:
        raise CreativeNotEditable
    return Planned(
        target=group,
        level=ManagedLevel.ADSET,
        external_id=external_id,
        action=ActionType.CREATE_AD,
        requested={
            **words,
            **picture,
            **form,
            "name": name,
            "source": copied.external_id,
            "source_form": copied.lead_form_external_id,
            "asset_id": asset_id,
        },
        previous=state_payload(group),
        dispatch=_dispatch_ad,
        revertible=False,
    )


def _dispatch_ad(log_id: str) -> None:
    from app.modules.ads.tasks import apply_new_ad_task

    apply_new_ad_task.delay(log_id)


def apply_new_ad(db: Session, *, log_id: str) -> str:
    """One audit row, carried out. Returns a word for the task's log line."""
    from app.modules.ads.actions.executor import Write, carry_out

    return carry_out(
        db,
        log_id=log_id,
        kind=Write(
            actions=frozenset({ActionType.CREATE_AD}),
            ready=_ad_ready,
            check=_check_ad,
            write=_write_ad,
            finish=_finish_ad,
        ),
    )


def _ad_ready(_db: Session, _log: ActionLog, target: Any) -> str:
    return "" if isinstance(target, AdSet) else "gone"


def _check_ad(_db: Session, job: Any) -> str:
    if job.before.delivery == FINISHED:
        return "finished"
    picture = str((job.log.request_payload or {}).get("image_hash") or "")
    if job.dry_run or not picture:
        return ""
    try:
        foreign = foreign_pictures(
            provider=job.log.target_provider,
            account_id=job.account.external_id,
            hashes=[picture],
            token=job.token,
        )
    except ProviderError:
        logger.info("could not read the pictures of %s", job.account.external_id)
        return "read"
    return FOREIGN_PICTURE if foreign else ""


def _write_ad(db: Session, job: Any) -> ActionResult:
    asked = job.log.request_payload
    copied = source_ad(
        db,
        owner=job.log.owner,
        group=job.target,
        external_id=str(asked["source"]),
    )
    story = story_of(db, owner=job.log.owner, ad=copied)
    launcher = MetaLauncher()
    name = str(asked["name"])
    if story is None:
        return _repeated(job, copied=copied, launcher=launcher, name=name)
    revised = restage(
        story,
        message=asked.get("message"),
        headline=asked.get("headline"),
        description=asked.get("description"),
        **_frame(asked=asked, token=job.token, dry_run=job.dry_run),
        lead_form_id=str(asked.get("lead_form_id") or ""),
    )
    creative = launcher.restage_creative(
        account=_account_ref(job),
        name=name,
        story=revised,
        token=job.token,
        dry_run=job.dry_run,
    )
    try:
        made = launcher.create_ad(
            account=_account_ref(job),
            adset=job.ref,
            creative=creative.ref,
            name=name,
            token=job.token,
            dry_run=job.dry_run,
            status=STATUS_PAUSED,
        )
    except ProviderError:
        _sweep(
            launcher=launcher, ref=creative.ref, token=job.token, dry_run=job.dry_run
        )
        raise
    return ActionResult(
        ok=True,
        ref=job.ref,
        applied={"ad": made.ref.id, "creative": creative.ref.id, "name": name},
        dry_run=job.dry_run,
    )


def _repeated(
    job: Any, *, copied: Ad, launcher: MetaLauncher, name: str
) -> ActionResult:
    """An advert that runs a post: the same creative, in one more advert."""
    creative = ExternalRef(
        provider=job.log.target_provider,
        level="creative",
        id=copied.creative_external_id,
    )  # type: ignore[arg-type]
    made = launcher.create_ad(
        account=_account_ref(job),
        adset=job.ref,
        creative=creative,
        name=name,
        token=job.token,
        dry_run=job.dry_run,
        status=STATUS_PAUSED,
    )
    return ActionResult(
        ok=True,
        ref=job.ref,
        applied={"ad": made.ref.id, "creative": creative.id, "name": name},
        dry_run=job.dry_run,
    )


def _finish_ad(db: Session, job: Any, result: ActionResult) -> None:
    asked = job.log.request_payload
    _upsert(
        db,
        Ad,
        owner=job.log.owner,
        provider=job.log.target_provider,
        external_id=str(result.applied["ad"]),
        label="ad",
        refused=[],
        defaults={
            "owner_id": job.log.owner_id,
            "adset_id": job.target.id,
            "name": str(asked["name"]),
            "status": STATUS_PAUSED,
            "effective_status": STATUS_PAUSED,
            "delivery": PAUSED,
            "creative_external_id": str(result.applied["creative"]),
            "lead_form_external_id": str(
                asked.get("lead_form_id") or asked.get("source_form") or ""
            ),
            "synced_at": utcnow(),
        },
    )
    _settled(db, job=job, result=result)


__all__ = [
    "apply_new_ad",
    "apply_new_group",
    "group_spec",
    "plan_new_ad",
    "plan_new_group",
    "source_ad",
    "source_group",
    "story_of",
]
