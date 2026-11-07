"""TZ 2: copies of what runs - a campaign, a group, an advert - made by Meta.

Meta copies a campaign alone, then each group alone, then each advert into
its group: an advert's copy is the only one that takes creative parameters,
and every copied creative must refuse Meta's creative changes (TZ 7.1). The
task runs in the background and the screen follows it as any change. A copy
that fails half way is taken back.

A campaign's and a group's copy is paused - the owner checks it and turns it
on. An advert put into a group that already runs is made active at once;
into a new group, paused.

An advert may be copied with a new creative instead (TZ 2.3): a picture or a
video from the account's library, other words, another form, another word on
the button. Meta's copy cannot take a new picture, so that one is built the
way a new advert is - the story restaged, a creative made with every Meta
change refused (TZ 7), and an advert made around it.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from adskit import ExternalRef
from adskit.dto import ActionResult
from adskit.errors import ProviderError
from metaads import PROVIDER
from metaads.campaigns import REMOVED_STATUSES
from metaads.copies import (
    ACTIVE,
    INHERITED,
    PAUSED,
    StatusOption,
    copy_ad,
    copy_adset,
    copy_campaign,
)
from metaads.enhancements import FEATURES_KEY, opted_out
from metaads.launcher import MetaLauncher
from metaads.restage import button_of, restage
from metaads.writes import delete_object
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import BUDGET_AT_CAMPAIGN, ManagedLevel
from app.modules.ads.exceptions import (
    AdditionNotOffered,
    ButtonNotOffered,
    CampaignFinished,
    CreativeNotEditable,
    UnknownTarget,
)
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.selectors.actions import managed_target
from app.modules.ads.services.additions import (
    _account_ref,
    _not_finished,
    _settled,
    budget_holder,
    story_of,
)
from app.modules.ads.services.manage import (
    ADDITION,
    Planned,
    _live,
    state_payload,
    target_for,
)
from app.modules.ads.services.swap import (
    FOREIGN_PICTURE,
    _form,
    _frame,
    _greeting,
    _picture,
    _sweep,
    foreign_pictures,
    welcome_plan,
)
from app.modules.audit.constants import ActionType
from app.modules.audit.models import ActionLog
from core.agent.guardrails import FINISHED
from core.targeting.buttons import buttons_for, kept_destination

logger = logging.getLogger(__name__)


def _opted_out() -> dict[str, Any]:
    """TZ 7.1 on a copy: the creative it makes refuses every Meta change.

    Meta's own copy example overwrites ``degrees_of_freedom_spec`` through
    ``creative_parameters``; the block replaces the original's whole.
    """
    return {FEATURES_KEY: opted_out()[FEATURES_KEY]}


# TZ 2.1: the copy's name, the original's with this after it.
COPY_SUFFIX: Final = " — nusxa"
# An advert's copy put into a new group of its own (TZ 2.3).
NEW_GROUP: Final = "new"
COPIES: Final = frozenset(
    {ActionType.COPY_CAMPAIGN, ActionType.COPY_ADSET, ActionType.COPY_AD}
)


def _copyable(target: Any) -> None:
    if target.provider != PROVIDER:
        raise AdditionNotOffered
    if str(target.delivery) == FINISHED:
        raise CampaignFinished


def _kept(rows: Any) -> list[Any]:
    """What Meta still holds: a deleted or archived object cannot be copied."""
    return [row for row in rows if str(row.status).upper() not in REMOVED_STATUSES]


# -- planning --------------------------------------------------------------------------


def plan_copy_campaign(db: Session, *, user: User, external_id: str) -> Planned:
    """TZ 2.1: the campaign with its groups and adverts, paused."""
    _live(db, user)
    campaign = target_for(
        db,
        user=user,
        level=ManagedLevel.CAMPAIGN,
        external_id=external_id,
        aspect=ADDITION,
    )
    _copyable(campaign)
    return Planned(
        target=campaign,
        level=ManagedLevel.CAMPAIGN,
        external_id=external_id,
        action=ActionType.COPY_CAMPAIGN,
        requested={"suffix": COPY_SUFFIX},
        previous=state_payload(campaign),
        dispatch=_dispatch,
        revertible=False,
    )


def plan_copy_adset(
    db: Session, *, user: User, external_id: str, campaign: str = ""
) -> Planned:
    """TZ 2.2: the group with its adverts, paused, into this or another campaign."""
    _live(db, user)
    group = target_for(
        db,
        user=user,
        level=ManagedLevel.ADSET,
        external_id=external_id,
        aspect=ADDITION,
    )
    _copyable(group)
    into = group.campaign
    if campaign and campaign != into.external_id:
        into = _own_campaign(db, user=user, external_id=campaign, beside=group)
    return Planned(
        target=group,
        level=ManagedLevel.ADSET,
        external_id=external_id,
        action=ActionType.COPY_ADSET,
        requested={"campaign": into.external_id, "suffix": COPY_SUFFIX},
        previous=state_payload(group),
        dispatch=_dispatch,
        revertible=False,
    )


def plan_copy_ad(
    db: Session,
    *,
    user: User,
    external_id: str,
    adset: str = "",
    creative: Mapping[str, Any] | None = None,
) -> Planned:
    """TZ 2.3: the advert into its group, another of the campaign's, or a new one.

    ``creative`` asks for a new one: ``message``, ``headline`` and
    ``description`` (``None`` keeps the line), ``asset_id`` from the library,
    ``lead_form_id``, ``button`` and a chat advert's ``welcome``. Left out,
    the creative is the original's.
    """
    _live(db, user)
    ad = target_for(
        db,
        user=user,
        level=ManagedLevel.AD,
        external_id=external_id,
        aspect=ADDITION,
    )
    _copyable(ad)
    group = ad.adset
    if adset == NEW_GROUP:
        into, status = NEW_GROUP, PAUSED
    else:
        found = group if not adset or adset == group.external_id else None
        if found is None:
            found = next(
                (row for row in group.campaign.adsets if row.external_id == adset),
                None,
            )
        if found is None or str(found.status).upper() in REMOVED_STATUSES:
            raise UnknownTarget
        into, status = found.external_id, ACTIVE
    asked: dict[str, Any] = {"adset": into, "status": status, "suffix": COPY_SUFFIX}
    if creative is not None:
        asked["creative"] = _new_creative(db, user=user, ad=ad, asked=creative)
    return Planned(
        target=ad,
        level=ManagedLevel.AD,
        external_id=external_id,
        action=ActionType.COPY_AD,
        requested=asked,
        previous=state_payload(ad),
        dispatch=_dispatch,
        revertible=False,
    )


def _new_creative(
    db: Session, *, user: User, ad: Ad, asked: Mapping[str, Any]
) -> dict[str, Any]:
    """What the new creative changes, checked the way an advert's edit is."""
    story = story_of(db, owner=user, ad=ad)
    if story is None:
        raise CreativeNotEditable
    asset_id = str(asked.get("asset_id") or "")
    words = {name: asked.get(name) for name in ("message", "headline", "description")}
    button = str(asked.get("button") or "")
    current = button_of(story)
    if button == str(current.get("type") or ""):
        button = ""
    if button and button not in offered_buttons(story):
        raise ButtonNotOffered
    return {
        **words,
        **_picture(db, owner=user, asset_id=asset_id),
        **_form(
            db,
            owner=user,
            ad=ad,
            lead_form_id=str(asked.get("lead_form_id") or ""),
        ),
        **welcome_plan(story, asked.get("welcome")),
        "asset_id": asset_id,
        "button": button,
        "name": f"{ad.name}{COPY_SUFFIX}",
    }


def offered_buttons(story: Mapping[str, Any] | None) -> tuple[str, ...]:
    """The words the button may take: its own first, then its kind's (TZ 2.3)."""
    current = button_of(story)
    own = str(current.get("type") or "")
    kind = kept_destination(current=current)
    others = (
        [row.key for row in buttons_for(provider=PROVIDER, sends_to=kind)]
        if kind
        else []
    )
    return tuple(dict.fromkeys([key for key in (own, *others) if key]))


def plan_copy(
    db: Session,
    *,
    user: User,
    level: str,
    external_id: str,
    into: str = "",
    creative: Mapping[str, Any] | None = None,
) -> Planned:
    """One of the three, by the level asked for."""
    if level == ManagedLevel.CAMPAIGN:
        return plan_copy_campaign(db, user=user, external_id=external_id)
    if level == ManagedLevel.ADSET:
        return plan_copy_adset(db, user=user, external_id=external_id, campaign=into)
    if level == ManagedLevel.AD:
        return plan_copy_ad(
            db, user=user, external_id=external_id, adset=into, creative=creative
        )
    raise UnknownTarget


def _own_campaign(
    db: Session, *, user: User, external_id: str, beside: AdSet
) -> Campaign:
    """Another of the owner's campaigns, on the same ad account."""
    found = managed_target(
        db, owner=user, level=ManagedLevel.CAMPAIGN, external_id=external_id
    )
    if (
        not isinstance(found, Campaign)
        or found.provider != beside.provider
        or found.ad_account_id != beside.campaign.ad_account_id
        or str(found.delivery) == FINISHED
        or not same_budget(found, beside.campaign)
    ):
        raise UnknownTarget
    return found


def same_budget(one: Campaign, other: Campaign) -> bool:
    """A group keeps its budget model: own budget, the campaign's, or a lifetime one.

    A campaign with no budget and no groups yet says nothing about it, and
    takes any group whose budget is its own.
    """
    theirs, ours = budget_holder(campaign=one), budget_holder(campaign=other)
    if one.daily_budget_minor is None and not one.adsets:
        return ours != BUDGET_AT_CAMPAIGN
    return theirs == ours


def _dispatch(log_id: str) -> None:
    from app.modules.ads.tasks import apply_copy_task

    apply_copy_task.delay(log_id)


# -- carrying out ----------------------------------------------------------------------


def apply_copy(db: Session, *, log_id: str) -> str:
    """One audit row, carried out. Returns a word for the task's log line."""
    from app.modules.ads.actions.executor import Write, carry_out

    return carry_out(
        db,
        log_id=log_id,
        kind=Write(
            actions=COPIES,
            ready=_ready,
            check=_check,
            write=_write,
            finish=_finish,
        ),
    )


def _ready(_db: Session, log: ActionLog, target: Any) -> str:
    wanted = {
        ActionType.COPY_CAMPAIGN: Campaign,
        ActionType.COPY_ADSET: AdSet,
        ActionType.COPY_AD: Ad,
    }[log.action]
    return "" if isinstance(target, wanted) else "gone"


def _check(db: Session, job: Any) -> str:
    """Not finished, and a new picture is the account's own (as a new advert's)."""
    refused = _not_finished(db, job)
    creative = (job.log.request_payload or {}).get("creative") or {}
    picture = str(creative.get("image_hash") or "")
    if refused or job.dry_run or not picture:
        return refused
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


@dataclass(frozen=True, slots=True)
class _Meta:
    token: str
    dry_run: bool


def _write(db: Session, job: Any) -> ActionResult:
    asked = job.log.request_payload
    meta = _Meta(token=job.token, dry_run=job.dry_run)
    suffix = str(asked.get("suffix") or "")
    if job.log.action == ActionType.COPY_CAMPAIGN:
        applied = _campaign(job.target, suffix=suffix, meta=meta)
    elif job.log.action == ActionType.COPY_ADSET:
        made = _group(
            job.target,
            campaign=str(asked["campaign"]),
            status=PAUSED,
            suffix=suffix,
            meta=meta,
        )
        applied = {"adset": made}
    elif asked.get("creative"):
        applied = _advert_anew(
            db, job, into=str(asked["adset"]), status=asked["status"]
        )
    else:
        applied = _advert(
            job.target,
            into=str(asked["adset"]),
            status=asked["status"],
            suffix=suffix,
            meta=meta,
        )
    return ActionResult(ok=True, ref=job.ref, applied=applied, dry_run=job.dry_run)


def _campaign(source: Campaign, *, suffix: str, meta: _Meta) -> dict[str, Any]:
    made = copy_campaign(
        campaign_id=source.external_id,
        suffix=suffix,
        token=meta.token,
        dry_run=meta.dry_run,
    )
    groups = _kept(source.adsets)
    try:
        for group in groups:
            _group(group, campaign=made, status=INHERITED, suffix="", meta=meta)
    except Exception:
        _remove(made, meta=meta)
        raise
    return {"campaign": made, "adsets": len(groups)}


def _group(
    source: AdSet, *, campaign: str, status: StatusOption, suffix: str, meta: _Meta
) -> str:
    """One group into ``campaign``, then each of its adverts.

    Not one deep copy: a group's copy cannot be given creative parameters, and
    every advert copied here must carry Meta's creative changes refused (TZ 7.1).
    """
    made = copy_adset(
        adset_id=source.external_id,
        campaign_id=campaign,
        deep_copy=False,
        status=status,
        suffix=suffix,
        token=meta.token,
        dry_run=meta.dry_run,
    )
    try:
        for ad in _kept(source.ads):
            copy_ad(
                ad_id=ad.external_id,
                adset_id=made,
                status=INHERITED,
                creative=_opted_out(),
                token=meta.token,
                dry_run=meta.dry_run,
            )
    except Exception:
        _remove(made, meta=meta)
        raise
    return made


def _remove(object_id: str, *, meta: _Meta) -> None:
    """A copy that failed half way is taken back, so a retry does not leave two."""
    try:
        delete_object(object_id=object_id, token=meta.token, dry_run=meta.dry_run)
    except Exception:
        logger.exception("could not remove the half-made copy %s", object_id)


def _new_group(source: Ad, *, into: str, meta: _Meta) -> str:
    """The group named, or a paused copy of the advert's own made for it."""
    if into != NEW_GROUP:
        return into
    return copy_adset(
        adset_id=source.adset.external_id,
        deep_copy=False,
        status=PAUSED,
        suffix=COPY_SUFFIX,
        token=meta.token,
        dry_run=meta.dry_run,
    )


def _advert(
    source: Ad, *, into: str, status: StatusOption, suffix: str, meta: _Meta
) -> dict[str, Any]:
    group = _new_group(source, into=into, meta=meta)
    try:
        made = copy_ad(
            ad_id=source.external_id,
            adset_id=group,
            status=status,
            suffix=suffix,
            creative=_opted_out(),
            token=meta.token,
            dry_run=meta.dry_run,
        )
    except Exception:
        if into == NEW_GROUP:
            _remove(group, meta=meta)
        raise
    return {"ad": made, "adset": group, "status": status}


def _advert_anew(
    db: Session, job: Any, *, into: str, status: StatusOption
) -> dict[str, Any]:
    """A new creative from the original's story, in a new advert (TZ 2.3)."""
    asked = job.log.request_payload["creative"]
    source: Ad = job.target
    story = story_of(db, owner=job.log.owner, ad=source)
    revised = restage(
        story or {},
        message=asked.get("message"),
        headline=asked.get("headline"),
        description=asked.get("description"),
        **_frame(asked=asked, token=job.token, dry_run=job.dry_run),
        lead_form_id=str(asked.get("lead_form_id") or ""),
        button=str(asked.get("button") or ""),
        **_greeting(asked),
    )
    meta = _Meta(token=job.token, dry_run=job.dry_run)
    account = _account_ref(job)
    launcher = MetaLauncher()
    name = str(asked["name"])
    creative = launcher.restage_creative(
        account=account,
        name=name,
        story=revised,
        token=job.token,
        dry_run=job.dry_run,
    )
    try:
        group = _new_group(source, into=into, meta=meta)
    except Exception:
        _sweep(
            launcher=launcher, ref=creative.ref, token=job.token, dry_run=job.dry_run
        )
        raise
    try:
        made = launcher.create_ad(
            account=account,
            adset=ExternalRef(
                provider=job.log.target_provider, level="adset", id=group
            ),
            creative=creative.ref,
            name=name,
            token=job.token,
            dry_run=job.dry_run,
            status=status,
        )
    except Exception:
        _sweep(
            launcher=launcher, ref=creative.ref, token=job.token, dry_run=job.dry_run
        )
        if into == NEW_GROUP:
            _remove(group, meta=meta)
        raise
    return {
        "ad": made.ref.id,
        "adset": group,
        "creative": creative.ref.id,
        "status": status,
    }


def _finish(db: Session, job: Any, result: ActionResult) -> None:
    """The copies reach the mirror with the next read, queued here."""
    _settled(db, job=job, result=result)


__all__ = [
    "COPIES",
    "COPY_SUFFIX",
    "NEW_GROUP",
    "apply_copy",
    "offered_buttons",
    "plan_copy",
    "plan_copy_ad",
    "plan_copy_adset",
    "plan_copy_campaign",
    "same_budget",
]
