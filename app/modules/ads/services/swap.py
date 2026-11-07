"""Replacing what one advert says or shows, by making the next one and stopping this one."""

import logging
import uuid
from collections.abc import Iterable
from typing import Any

from adskit import ExternalRef
from adskit.dto import ActionResult, StatusDTO
from adskit.errors import InvalidRequest, ProviderError
from metaads import welcome as greeting
from metaads.assets import MetaAssets
from metaads.launcher import MetaLauncher
from metaads.restage import changed, restage, welcome_of
from metaads.specs import STATUS_ACTIVE, STATUS_PAUSED
from metaads.writes import set_creative
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel, MediaKind
from app.modules.ads.exceptions import (
    CampaignFinished,
    ChangeRefused,
    CreativeNotEditable,
    LearningInProgress,
    NothingChanged,
    UnknownLeadForm,
    UnknownMedia,
    WelcomeNotOffered,
    WelcomeRefused,
)
from app.modules.ads.models import Ad, MediaAsset
from app.modules.ads.services.manage import (
    CREATIVE,
    Planned,
    _ad_context,
    record,
    state_of,
    state_payload,
    target_for,
)
from app.modules.audit.constants import ActionType
from app.modules.audit.models import ActionLog
from app.modules.integrations.models import PageAccount
from core.agent import AdContext, ObjectState, check_creative_swap
from core.agent.guardrails import PAUSED, REFUSED_FINISHED, REFUSED_LEARNING

logger = logging.getLogger(__name__)

LEVEL = ManagedLevel.AD
SWAPPABLE_KINDS: tuple[str, ...] = (MediaKind.IMAGE, MediaKind.VIDEO)
REFUSALS: dict[str, type[Exception]] = {
    REFUSED_FINISHED: CampaignFinished,
    REFUSED_LEARNING: LearningInProgress,
}
NAME_SUFFIX = " · yangi"
FOREIGN_PICTURE = "foreign_picture"


def form_page(db: Session, *, owner: User, ad: Ad) -> PageAccount | None:
    """The page of the form this advert opens, or nothing."""
    from app.modules.leads.selectors import forms_by_external_id

    if not ad.lead_form_external_id:
        return None
    row = forms_by_external_id(
        db, owner=owner, provider=ad.provider, external_ids=[ad.lead_form_external_id]
    ).get(ad.lead_form_external_id)
    return row.page if row is not None else None


def parent_external_id(*, target: Any) -> str:
    """The group this advert sits in, as the provider names it."""
    parent = getattr(target, "adset", None)
    return str(getattr(parent, "external_id", "") or "")


def foreign_pictures(
    *, provider: str, account_id: str, hashes: Iterable[str], token: str
) -> frozenset[str]:
    """The hashes among these that this ad account does not hold itself."""
    wanted = [value for value in dict.fromkeys(hashes) if value]
    if not wanted:
        return frozenset()
    account = ExternalRef(provider=provider, level="account", id=account_id)  # type: ignore[arg-type]
    owned = MetaAssets().own_images(account=account, hashes=wanted, token=token)
    return frozenset(wanted) - owned


def plan_swap(
    db: Session,
    *,
    user: User,
    external_id: str,
    message: str | None = None,
    headline: str | None = None,
    description: str | None = None,
    asset_id: str = "",
    lead_form_id: str = "",
    welcome: dict[str, Any] | None = None,
    in_place: bool = False,
) -> Planned:
    """Replace what one advert says, by making the next one.

    ``in_place`` (TZ 2.4) keeps the advert and gives it the new creative:
    Meta reviews it again and its likes and comments start from nothing.
    ``welcome`` is a chat advert's greeting (TZ 2.5): ``text`` and
    ``questions`` of ``title`` and ``response``.
    """
    from app.modules.ads.selectors import creative_of
    from app.modules.billing.services import require_live_subscription

    require_live_subscription(db, owner=user)
    target = target_for(
        db, user=user, level=LEVEL, external_id=external_id, aspect=CREATIVE
    )
    creative = creative_of(db, owner=user, ad=target)
    story = getattr(creative, "story_raw", None)
    if creative is None or not isinstance(story, dict) or not story:
        raise CreativeNotEditable
    picture = _picture(db, owner=user, asset_id=asset_id)
    form = _form(db, owner=user, ad=target, lead_form_id=lead_form_id)
    words = {"message": message, "headline": headline, "description": description}
    chat = welcome_plan(story, welcome)
    if not changed(story, **words, **picture, **form, **_greeting(chat)):
        raise NothingChanged
    context = _ad_context(db, owner=user, target=target)
    verdict = check_creative_swap(
        state=state_of(target),
        parent=AdContext(
            parent_is_learning=context.parent_is_learning,
            other_active_ads=context.other_active_ads,
        ),
    )
    if not verdict.allowed:
        raise REFUSALS.get(verdict.reason, ChangeRefused)()
    return Planned(
        target=target,
        level=LEVEL,
        external_id=external_id,
        action=ActionType.CREATIVE_SWAP,
        requested={
            **words,
            **picture,
            **form,
            **chat,
            "asset_id": asset_id,
            "in_place": in_place,
        },
        previous=state_payload(target) | {"creative": creative.external_id},
        dispatch=_dispatch,
        revertible=False,
    )


def welcome_plan(story: dict[str, Any], asked: dict[str, Any] | None) -> dict[str, Any]:
    """The greeting asked for, checked; nothing when none was asked."""
    if asked is None:
        return {}
    now = welcome_of(story)
    if now is None:
        raise WelcomeNotOffered
    text = str(asked.get("text") or "")
    rows = [
        {
            "title": str(row.get("title") or ""),
            "response": str(row.get("response") or ""),
        }
        for row in asked.get("questions") or ()
    ]
    wanted = greeting.from_rows(text, rows)
    try:
        greeting.checked(wanted)
    except InvalidRequest as exc:
        raise WelcomeRefused from exc
    if wanted == now:
        # Sent back as it is: rewriting it would still be a new creative.
        return {}
    return {"welcome": {"text": text, "questions": rows}}


def _greeting(asked: dict[str, Any]) -> dict[str, Any]:
    """The restage argument for a stored ``welcome``; nothing when none."""
    found = asked.get("welcome")
    if not isinstance(found, dict):
        return {}
    return {
        "welcome": greeting.from_rows(
            str(found.get("text") or ""), found.get("questions") or []
        )
    }


def _picture(db: Session, *, owner: User, asset_id: str) -> dict[str, str]:
    if not asset_id:
        return {}
    try:
        key = uuid.UUID(str(asset_id))
    except ValueError as exc:
        raise UnknownMedia from exc
    asset = db.scalar(
        select(MediaAsset).where(
            MediaAsset.owner_id == owner.id,
            MediaAsset.id == key,
            MediaAsset.kind.in_(SWAPPABLE_KINDS),
        )
    )
    if asset is None:
        raise UnknownMedia
    if asset.kind == MediaKind.VIDEO:
        return {"video_id": asset.external_id, "thumbnail_url": asset.thumbnail_url}
    return {"image_hash": asset.external_id}


def _form(db: Session, *, owner: User, ad: Ad, lead_form_id: str) -> dict[str, str]:
    from app.modules.leads.selectors import collecting_form

    if not lead_form_id:
        return {}
    page = form_page(db, owner=owner, ad=ad)
    if page is None:
        raise UnknownLeadForm
    if collecting_form(db, owner=owner, page=page, external_id=lead_form_id) is None:
        raise UnknownLeadForm
    return {"lead_form_id": lead_form_id}


def _dispatch(log_id: str) -> None:
    from app.modules.ads.tasks import apply_swap_task

    apply_swap_task.delay(log_id)


def apply_swap(db: Session, *, log_id: str) -> str:
    """One audit row, carried out. Returns a word for the task's log line."""
    from app.modules.ads.actions.executor import Write, carry_out

    return carry_out(
        db,
        log_id=log_id,
        kind=Write(
            actions=frozenset({ActionType.CREATIVE_SWAP}),
            ready=_swappable,
            check=_check_swap,
            write=_write_swap,
            finish=_finish_swap,
        ),
    )


def _swappable(db: Session, log: ActionLog, target: Any) -> str:
    """An advert in the mirror with a stored creative to build the next one from."""
    from app.modules.ads.selectors import creative_of

    if not isinstance(target, Ad):
        return "gone"
    creative = creative_of(db, owner=log.owner, ad=target)
    story = getattr(creative, "story_raw", None)
    return "" if isinstance(story, dict) and story else "creative"


def _check_swap(db: Session, job: Any) -> str:
    return swap_refusal(
        db,
        log=job.log,
        before=job.before,
        target=job.target,
        port=job.provider.campaigns,
        account_id=job.account.external_id,
        token=job.token,
        dry_run=job.dry_run,
    )


def _write_swap(db: Session, job: Any) -> ActionResult:
    from app.modules.ads.selectors import creative_of

    creative = creative_of(db, owner=job.log.owner, ad=job.target)
    return _swap(
        log=job.log,
        target=job.target,
        story=creative.story_raw,
        account_id=job.account.external_id,
        adset_id=parent_external_id(target=job.target),
        port=job.provider.campaigns,
        ref=job.ref,
        before=job.before,
        token=job.token,
        dry_run=job.dry_run,
    )


def _finish_swap(db: Session, job: Any, result: ActionResult) -> None:
    port = job.provider.campaigns
    after = None if job.dry_run else _read_back(port=port, ref=job.ref, token=job.token)
    record(
        db,
        log=job.log,
        target=job.target,
        result=result,
        before=job.before,
        after=after,
    )
    if result.applied.get("in_place") and not job.dry_run:
        # The advert's new creative reaches the mirror with the next read.
        from app.modules.ads.services.mirror import _queue

        _queue(db, job.account)


def swap_refusal(
    db: Session,
    *,
    log: ActionLog,
    before: Any,
    target: Ad,
    port: Any,
    account_id: str,
    token: str,
    dry_run: bool,
) -> str:
    """The guardrail's verdict on what the provider says right now."""
    parent_id = parent_external_id(target=target)
    if not parent_id:
        return "gone"
    parent_ref = ExternalRef(
        provider=log.target_provider, level=ManagedLevel.ADSET, id=parent_id
    )  # type: ignore[arg-type]
    picture = str((log.request_payload or {}).get("image_hash") or "")
    try:
        parent = port.get_status(ref=parent_ref, token=token)
        foreign = not dry_run and foreign_pictures(
            provider=log.target_provider,
            account_id=account_id,
            hashes=[picture],
            token=token,
        )
    except ProviderError:
        logger.info("could not read %s before restaging an advert", parent_ref)
        return "read"
    if foreign:
        return FOREIGN_PICTURE
    context = _ad_context(db, owner=log.owner, target=target)
    verdict = check_creative_swap(
        state=ObjectState(delivery=before.delivery, is_learning=before.is_learning),
        parent=AdContext(
            parent_is_learning=parent.is_learning,
            other_active_ads=context.other_active_ads,
        ),
    )
    return "" if verdict.allowed else verdict.reason


def _swap(
    *,
    log: ActionLog,
    target: Ad,
    story: dict[str, Any],
    account_id: str,
    adset_id: str,
    port: Any,
    ref: ExternalRef,
    before: StatusDTO,
    token: str,
    dry_run: bool,
) -> ActionResult:
    """The three calls, in the one order that cannot leave a group dark."""
    launcher = MetaLauncher()
    asked = log.request_payload or {}
    revised = restage(
        story,
        message=asked.get("message"),
        headline=asked.get("headline"),
        description=asked.get("description"),
        **_frame(asked=asked, token=token, dry_run=dry_run),
        lead_form_id=str(asked.get("lead_form_id") or ""),
        **_greeting(asked),
    )
    account_ref = ExternalRef(
        provider=log.target_provider, level="account", id=account_id
    )  # type: ignore[arg-type]
    creative = launcher.restage_creative(
        account=account_ref,
        name=f"{target.name}{NAME_SUFFIX}",
        story=revised,
        token=token,
        dry_run=dry_run,
    )
    if asked.get("in_place"):
        return _in_place(
            launcher=launcher,
            ref=ref,
            creative=creative.ref,
            token=token,
            dry_run=dry_run,
        )
    try:
        made = launcher.create_ad(
            account=account_ref,
            adset=ExternalRef(
                provider=log.target_provider, level=ManagedLevel.ADSET, id=adset_id
            ),  # type: ignore[arg-type]
            creative=creative.ref,
            name=f"{target.name}{NAME_SUFFIX}",
            token=token,
            dry_run=dry_run,
            status=STATUS_ACTIVE if before.status == STATUS_ACTIVE else STATUS_PAUSED,
        )
    except ProviderError:
        _sweep(launcher=launcher, ref=creative.ref, token=token, dry_run=dry_run)
        raise
    try:
        port.set_status(ref=ref, status=PAUSED, token=token, dry_run=dry_run)
    except ProviderError:
        if not _stopped_anyway(port=port, ref=ref, token=token):
            for each in (made.ref, creative.ref):
                _sweep(launcher=launcher, ref=each, token=token, dry_run=dry_run)
            raise
    return ActionResult(
        ok=True,
        ref=ref,
        applied={"creative": creative.ref.id, "ad": made.ref.id, "status": PAUSED},
        dry_run=dry_run,
    )


def _in_place(
    *,
    launcher: MetaLauncher,
    ref: ExternalRef,
    creative: ExternalRef,
    token: str,
    dry_run: bool,
) -> ActionResult:
    """TZ 2.4 «Shu e'londa»: the same advert, showing the new creative."""
    try:
        set_creative(
            ad_id=ref.id, creative_id=creative.id, token=token, dry_run=dry_run
        )
    except ProviderError:
        _sweep(launcher=launcher, ref=creative, token=token, dry_run=dry_run)
        raise
    return ActionResult(
        ok=True,
        ref=ref,
        applied={"creative": creative.id, "in_place": True},
        dry_run=dry_run,
    )


def _frame(*, asked: dict[str, Any], token: str, dry_run: bool) -> dict[str, str]:
    """The picture the new creative names, with a video's frame read fresh."""
    video_id = str(asked.get("video_id") or "")
    still = str(asked.get("thumbnail_url") or "")
    if video_id and not dry_run:
        frame = MetaAssets().video_thumbnail(video_id=video_id, token=token)
        still = frame or still
    return {
        "image_hash": str(asked.get("image_hash") or ""),
        "video_id": video_id,
        "thumbnail_url": still,
    }


def _sweep(
    *, launcher: MetaLauncher, ref: ExternalRef, token: str, dry_run: bool
) -> None:
    try:
        launcher.remove(ref=ref, token=token, dry_run=dry_run)
    except ProviderError:
        logger.exception("could not remove the creative %s", ref.id)


def _stopped_anyway(*, port: Any, ref: ExternalRef, token: str) -> bool:
    try:
        return port.get_status(ref=ref, token=token).status.upper() == PAUSED.upper()
    except ProviderError:
        return False


def _read_back(*, port: Any, ref: ExternalRef, token: str) -> Any:
    try:
        return port.get_status(ref=ref, token=token)
    except ProviderError:
        logger.info("could not read %s back after restaging it", ref.id)
        return None


__all__ = [
    "FOREIGN_PICTURE",
    "SWAPPABLE_KINDS",
    "apply_swap",
    "foreign_pictures",
    "form_page",
    "parent_external_id",
    "plan_swap",
    "swap_refusal",
]
