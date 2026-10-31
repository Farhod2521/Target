"""The provider calls, in the only order they can happen in: the files, the
campaign the goal shares, the ad groups, the lead form, the creatives and ads."""

import logging
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Final, Literal

from adskit import registry
from adskit.dto import ActionResult, AdDTO, AdSetDTO, CampaignDTO
from adskit.errors import NotFound, ProviderError, TemporaryFailure
from adskit.refs import ExternalRef, Level, ProviderName
from metaads.launcher import MetaLauncher
from metaads.leadforms import questions_for
from metaads.specs import (
    THANK_YOU_CALL,
    THANK_YOU_NONE,
    THANK_YOU_WEBSITE,
    CampaignSpec,
    CarouselCard,
    LeadFormSpec,
)
from metaads.specs import AdSetSpec as MetaAdSetSpec
from metaads.writes import changed_from
from metaads.writing import is_dry_run_id
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads import draft as draft_field
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import POSTS_NOT_PROMOTED, LaunchStatus, LaunchStep
from app.modules.ads.models import CampaignLaunch, GoalCampaign, LaunchCreative
from app.modules.ads.selectors.ad_groups import Arrangement, GroupCard, arrangement
from app.modules.ads.selectors.budget_level import budget_level, campaign_budget_minor
from app.modules.ads.selectors.media import post_account
from app.modules.ads.selectors.schedule import (
    effective_ad_name,
    effective_campaign_name,
    end_time_for,
    start_time_for,
)
from app.modules.ads.selectors.variants import launch_variants, promotes_post
from app.modules.ads.services import meta_specs
from app.modules.ads.services.launch import advance, starting
from app.modules.ads.services.launch_media import UploadedMedia, upload_all
from app.modules.ads.trace import LaunchTrace, NoTrace
from app.modules.businesses.models import Business
from app.modules.integrations.models import AdAccount, PageAccount
from core.targeting import BuiltTargeting

logger = logging.getLogger(__name__)
CLOCK_SKEW = timedelta(minutes=5)
FORM_LEVEL = "form"
GONE: Final = "gone"
STOPPED: Final = "stopped"
_CHOSEN_BY: dict[str, str] = {
    draft_field.BY_OWNER: "egasi tayyor formani tanladi",
    draft_field.BY_AI: "AI tayyor formani tanladi",
}
_CHOSEN_BY_UNKNOWN = "tayyor forma (manba noma'lum)"
type Listed = CampaignDTO | AdSetDTO | AdDTO
type MakeCampaign = Callable[[CampaignSpec], ExternalRef]
type SpecFor = Callable[[int], CampaignSpec]
type Unusable = Literal["gone", "stopped"]


def run_sequence(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    account: AdAccount,
    page: PageAccount,
    built: BuiltTargeting,
    token: str,
    page_token: str,
    dry_run: bool,
    attempt: int = 1,
    trace: LaunchTrace | None = None,
) -> None:
    """Create the files, the objects, and the form. Commits as it goes."""
    watch = trace or NoTrace()
    launcher = MetaLauncher()
    provider = ProviderName(launch.provider)
    account_ref = ExternalRef(
        provider=provider, level="account", id=account.external_id
    )
    page_ref = ExternalRef(provider=provider, level="page", id=page.external_id)
    variants = launch_variants(db, launch=launch)
    arrange = arrangement(db, launch=launch, business=business, variants=variants)
    watch.step(6, "Rasm yoki video yuklash")
    starting(db, launch, step=LaunchStep.IMAGE, watch=watch)
    watch.inputs(
        "manba",
        {
            "variants": len(variants),
            "media": [_source_of(variant) for variant in variants],
            "dry_run": dry_run,
        },
    )
    media = upload_all(
        db,
        launch=launch,
        account=account_ref,
        token=token,
        dry_run=dry_run,
        page=page,
        built=built,
    )
    watch.decision("natija", {"media": [asdict(item) for item in media]})
    advance(db, launch, step=LaunchStep.IMAGE, watch=watch)
    watch.step(7, "Kampaniya")
    starting(db, launch, step=LaunchStep.CAMPAIGN, watch=watch)
    with campaign_for(
        db,
        launch=launch,
        account=account,
        page=page,
        goal=str(launch.answers.get("goal") or ""),
        objective=built.objective,
        token=token,
        dry_run=dry_run,
        spec_for=lambda number: meta_specs.goal_campaign_spec(
            launch=launch, business=business, built=built, number=number
        ),
        make=lambda spec: _new_campaign(
            db,
            launch=launch,
            spec=spec,
            launcher=launcher,
            provider=provider,
            account_ref=account_ref,
            token=token,
            dry_run=dry_run,
            watch=watch,
        ),
        watch=watch,
    ) as campaign_ref:
        advance(db, launch, step=LaunchStep.CAMPAIGN, ref=campaign_ref, watch=watch)
        made = _adsets(
            db,
            launch=launch,
            business=business,
            account=account,
            page=page,
            built=built,
            arrange=arrange,
            campaign_id=campaign_ref.id,
            launcher=launcher,
            provider=provider,
            account_ref=account_ref,
            token=token,
            dry_run=dry_run,
            watch=watch,
        )
    watch.step(9, "Qaytarib o'qish - Meta nimani o'zgartirdi")
    for group, adset_spec, adset in made:
        prefix = f"{group.position + 1}-guruh"
        watch.decision(f"{prefix} · yuborilgan targeting", dict(adset_spec.targeting))
        watch.decision(f"{prefix} · tashlab yuborilgani (dropped)", adset.dropped)
        watch.decision(
            f"{prefix} · Meta qo'shgan yoki o'zgartirgan",
            changed_from(
                sent=dict(adset_spec.targeting),
                returned=adset.raw_response.get("targeting") or {},
            ),
        )
    form_ref: ExternalRef | None = None
    if not built.needs_lead_form:
        watch.step(10, "Lid formasi")
        watch.note("Bu maqsadda forma yo'q - bosqich kerak emas.")
    else:
        form_ref = lead_form(
            db,
            launch=launch,
            business=business,
            page=page,
            page_ref=page_ref,
            provider=provider,
            launcher=launcher,
            page_token=page_token,
            dry_run=dry_run,
            attempt=attempt,
            watch=watch,
        )
    watch.step(11, "Reklamalar")
    uploads = {
        variant.position: item for variant, item in zip(variants, media, strict=True)
    }
    for group, _spec, adset in made:
        for variant in group.variants:
            _one_ad(
                db,
                launch=launch,
                business=business,
                built=built,
                page=page,
                variant=variant,
                uploaded=uploads[variant.position],
                launcher=launcher,
                account_ref=account_ref,
                adset_ref=adset.ref,
                form_ref=form_ref,
                token=token,
                dry_run=dry_run,
                watch=watch,
            )


def _adsets(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    account: AdAccount,
    page: PageAccount,
    built: BuiltTargeting,
    arrange: Arrangement,
    campaign_id: str,
    launcher: MetaLauncher,
    provider: ProviderName,
    account_ref: ExternalRef,
    token: str,
    dry_run: bool,
    watch: LaunchTrace,
) -> list[tuple[GroupCard, MetaAdSetSpec, AdSetDTO]]:
    built_groups = arrange.filled
    watch.step(8, "Guruhlar (adset)")
    start_time = start_time_for(launch=launch, now=utcnow())
    end_time = end_time_for(launch=launch)
    watch.decision(
        "boshlanish",
        {
            "start_date": str(launch.start_date or ""),
            "account_timezone": account.timezone,
            "start_time": start_time,
            "end_time": end_time,
        },
    )
    watch.decision(
        "taqsimot",
        {
            "guruhlar": len(built_groups),
            "reklamalar": [group.size for group in built_groups],
            "byudjet": [group.daily_budget_minor for group in built_groups],
            "byudjet_darajasi": budget_level(launch=launch),
            "qo'lda": arrange.arranged,
        },
    )
    made: list[tuple[GroupCard, MetaAdSetSpec, AdSetDTO]] = []
    for group in built_groups:
        watch.substep(f"{group.position + 1}-guruh · {group.size} ta reklama")
        starting(db, launch, step=LaunchStep.ADSET, watch=watch)
        adset_spec = meta_specs.adset_spec(
            launch=launch,
            business=business,
            built=built,
            campaign_id=campaign_id,
            page_id=page.external_id,
            start_time=start_time,
            end_time=end_time,
            name=_adset_name(
                group=group, launch=launch, business=business, of=len(built_groups)
            ),
            daily_budget_minor=group.daily_budget_minor,
        )
        watch.inputs("spec", adset_spec.model_dump())
        with _reply_may_be_lost(
            db,
            launch=launch,
            step=LaunchStep.ADSET,
            level="adset",
            name=adset_spec.name,
            parent_id=campaign_id,
            provider=provider,
            account_ref=account_ref,
            token=token,
            watch=watch,
        ):
            adset = launcher.create_adset(
                account=account_ref, spec=adset_spec, token=token, dry_run=dry_run
            )
        advance(
            db,
            launch,
            step=LaunchStep.ADSET,
            ref=adset.ref,
            dropped=adset.dropped,
            watch=watch,
        )
        made.append((group, adset_spec, adset))
    return made


def _adset_name(
    *, group: GroupCard, launch: CampaignLaunch, business: Business, of: int
) -> str:
    if group.named or of > 1:
        return group.name
    return effective_campaign_name(launch=launch, business=business) or group.name


def _new_campaign(
    db: Session,
    *,
    launch: CampaignLaunch,
    spec: CampaignSpec,
    launcher: MetaLauncher,
    provider: ProviderName,
    account_ref: ExternalRef,
    token: str,
    dry_run: bool,
    watch: LaunchTrace,
) -> ExternalRef:
    with _reply_may_be_lost(
        db,
        launch=launch,
        step=LaunchStep.CAMPAIGN,
        level="campaign",
        name=spec.name,
        provider=provider,
        account_ref=account_ref,
        token=token,
        watch=watch,
    ):
        made = launcher.create_campaign(
            account=account_ref, spec=spec, token=token, dry_run=dry_run
        )
    return made.ref


@contextmanager
def _reply_may_be_lost(
    db: Session,
    *,
    launch: CampaignLaunch,
    step: str,
    level: Level,
    name: str,
    provider: ProviderName,
    account_ref: ExternalRef,
    token: str,
    watch: LaunchTrace,
    parent_id: str | None = None,
) -> Iterator[None]:
    """Wrap a create whose reply can go missing without the write going with it."""
    asked_at = utcnow()
    try:
        yield
    except TemporaryFailure:
        found = _made_anyway(
            provider=provider,
            level=level,
            name=name,
            parent_id=parent_id,
            since=asked_at - CLOCK_SKEW,
            account_ref=account_ref,
            token=token,
        )
        if found is not None:
            logger.warning(
                "launch %s: the %s was created and the reply was lost (%s)",
                launch.id,
                level,
                found.id,
            )
            watch.note(
                f"Meta javob bermadi, lekin obyektni yaratib qo'ygan ekan (`{found.id}`). "
                "Yozib olindi - tozalashda o'chiriladi."
            )
            advance(db, launch, step=step, ref=found, watch=watch)
        raise


def _made_anyway(
    *,
    provider: ProviderName,
    level: Level,
    name: str,
    parent_id: str | None,
    since: datetime,
    account_ref: ExternalRef,
    token: str,
) -> ExternalRef | None:
    reader = registry.get(provider).campaigns
    readers: dict[str, Callable[..., Sequence[Listed]]] = {
        "campaign": reader.list_campaigns,
        "adset": reader.list_adsets,
        "ad": reader.list_ads,
    }
    try:
        rows: Sequence[Listed] = readers[level](account=account_ref, token=token)
    except ProviderError as exc:
        logger.warning("could not ask whether the %s was made: %s", level, exc)
        return None
    except KeyError:
        return None
    for row in rows:
        if row.name == name and _made_here(row, parent_id=parent_id, since=since):
            return row.ref
    return None


def _made_here(row: Listed, *, parent_id: str | None, since: datetime) -> bool:
    if isinstance(row, AdSetDTO):
        return row.campaign_ref.id == parent_id
    if isinstance(row, AdDTO):
        return row.adset_ref.id == parent_id
    return row.created_time is not None and row.created_time >= since


def _one_ad(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    built: BuiltTargeting,
    page: PageAccount,
    variant: LaunchCreative,
    uploaded: UploadedMedia,
    launcher: MetaLauncher,
    account_ref: ExternalRef,
    adset_ref: ExternalRef,
    form_ref: ExternalRef | None,
    token: str,
    dry_run: bool,
    watch: LaunchTrace,
) -> None:
    """One variant: the creative, then the ad that shows it."""
    watch.substep(f"Reklama {variant.position + 1} · kreativ")
    starting(db, launch, step=LaunchStep.CREATIVE, watch=watch)
    creative = _creative(
        db,
        launch=launch,
        business=business,
        built=built,
        page=page,
        variant=variant,
        uploaded=uploaded,
        launcher=launcher,
        account_ref=account_ref,
        form_ref=form_ref,
        token=token,
        dry_run=dry_run,
        watch=watch,
    )
    advance(db, launch, step=LaunchStep.CREATIVE, ref=creative.ref, watch=watch)
    watch.substep(f"Reklama {variant.position + 1} · ad")
    starting(db, launch, step=LaunchStep.AD, watch=watch)
    name = effective_ad_name(launch=launch, business=business, variant=variant)
    watch.inputs(
        "spec", {"name": name, "adset_id": adset_ref.id, "creative_id": creative.ref.id}
    )
    with _reply_may_be_lost(
        db,
        launch=launch,
        step=LaunchStep.AD,
        level="ad",
        name=name,
        parent_id=adset_ref.id,
        provider=ProviderName(launch.provider),
        account_ref=account_ref,
        token=token,
        watch=watch,
    ):
        ad = launcher.create_ad(
            account=account_ref,
            adset=adset_ref,
            creative=creative.ref,
            name=name,
            token=token,
            dry_run=dry_run,
        )
    advance(db, launch, step=LaunchStep.AD, ref=ad.ref, watch=watch)


def _creative(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    built: BuiltTargeting,
    page: PageAccount,
    variant: LaunchCreative,
    uploaded: UploadedMedia,
    launcher: MetaLauncher,
    account_ref: ExternalRef,
    form_ref: ExternalRef | None,
    token: str,
    dry_run: bool,
    watch: LaunchTrace,
) -> ActionResult:
    """The creative, built one of the two ways a picture can reach an ad."""
    from app.modules.integrations.selectors.pages import instagram_handles

    form_id = form_ref.id if form_ref is not None else ""
    if promotes_post(variant=variant, built=built):
        account_of_post = post_account(asset=variant.media_asset, page=page)  # type: ignore[arg-type]
        spec = meta_specs.boost_spec(
            launch=launch,
            business=business,
            built=built,
            variant=variant,
            page_id=page.external_id,
            instagram_id=account_of_post,
            instagram_username=instagram_handles(db, page=page).get(
                account_of_post, ""
            ),
            form_id=form_id,
        )
        watch.inputs("spec (mavjud post)", spec.model_dump())
        boosted = launcher.boost_creative(
            account=account_ref, spec=spec, token=token, dry_run=dry_run
        )
        if not dry_run:
            check_promoted(
                db,
                launch=launch,
                variant=variant,
                creative=boosted.ref,
                launcher=launcher,
                token=token,
                watch=watch,
            )
        return boosted
    creative_spec = meta_specs.creative_spec(
        launch=launch,
        business=business,
        built=built,
        variant=variant,
        page_id=page.external_id,
        instagram_id=page.instagram_user_id,
        instagram_username=page.instagram_username,
        form_id=form_id,
        image_hash=uploaded.image_hash,
        video_id=uploaded.video_id,
        thumbnail_url=uploaded.thumbnail_url,
        cards=tuple(
            CarouselCard(
                image_hash=card.image_hash,
                video_id=card.video_id,
                thumbnail_url=card.thumbnail_url,
            )
            for card in uploaded.cards
        ),
    )
    watch.inputs("spec", creative_spec.model_dump())
    return launcher.create_creative(
        account=account_ref, spec=creative_spec, token=token, dry_run=dry_run
    )


def _source_of(variant: LaunchCreative) -> dict[str, object]:
    from app.common import storage

    size = storage.size(variant.media_upload) if variant.media_upload else None
    return {
        "position": str(variant.position),
        "media_asset_id": str(variant.media_asset_id or ""),
        "media_upload": variant.media_upload or "",
        "size_bytes": size,
        "size_mb": f"{size / 1048576:.1f}" if size is not None else "",
    }


def check_promoted(
    db: Session,
    *,
    launch: CampaignLaunch,
    variant: LaunchCreative,
    creative: ExternalRef,
    launcher: MetaLauncher,
    token: str,
    watch: LaunchTrace,
) -> None:
    """Whether the creative Meta kept still advertises the post we named."""
    asset = variant.media_asset
    wanted = asset.external_id if asset is not None else ""
    try:
        found = launcher.promoted_media(creative=creative, token=token)
    except ProviderError as exc:
        watch.note(
            f"Reklama {variant.position + 1}: postni tekshirib bo'lmadi ({exc})."
        )
        return
    watch.decision(
        f"Reklama {variant.position + 1} · post o'z joyidami",
        {"kutilgan": wanted, "meta_javobi": list(found)},
    )
    if wanted and wanted in found:
        return
    dropped = dict(launch.dropped or {})
    missed = dropped.get(POSTS_NOT_PROMOTED, [])
    launch.dropped = {**dropped, POSTS_NOT_PROMOTED: [*missed, variant.position]}
    db.commit()
    logger.warning(
        "launch %s: advert %s does not advertise post %s (Meta answered %s)",
        launch.id,
        variant.position,
        wanted,
        found,
    )


# -- the lead form ---------------------------------------------------------------------


def lead_form(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    page: PageAccount,
    page_ref: ExternalRef,
    provider: ProviderName,
    launcher: MetaLauncher,
    page_token: str,
    dry_run: bool,
    attempt: int,
    watch: LaunchTrace,
) -> ExternalRef:
    """The form, made or reused, and the row that makes it findable."""
    watch.step(10, "Lid formasi")
    starting(db, launch, step=LaunchStep.FORM, watch=watch)
    chosen = launch.lead_form_external_id
    if chosen:
        source = draft_field.source(launch.draft, draft_field.LEAD_FORM)
        watch.decision(
            _CHOSEN_BY.get(source, _CHOSEN_BY_UNKNOWN),
            {"form_id": chosen, "source": source},
        )
        advance(db, launch, step=LaunchStep.FORM, watch=watch)
        return ExternalRef(provider=provider, level=FORM_LEVEL, id=chosen)
    form_spec = meta_specs.form_spec(launch=launch, business=business, attempt=attempt)
    kept = ref_field.first_id(launch.created_refs or {}, LaunchStep.FORM)
    if kept and not is_dry_run_id(kept):
        watch.decision("oldingi urinishdan qayta ishlatildi", {"form_id": kept})
        form_ref = ExternalRef(provider=provider, level=FORM_LEVEL, id=kept)
    else:
        watch.inputs("spec", form_spec.model_dump())
        form = launcher.create_form(
            page=page_ref, spec=form_spec, page_token=page_token, dry_run=dry_run
        )
        form_ref = form.ref
    advance(db, launch, step=LaunchStep.FORM, ref=form_ref, watch=watch)
    if not dry_run:
        _remember_form(
            db,
            launch=launch,
            page=page,
            form_id=form_ref.id,
            spec=form_spec,
            watch=watch,
        )
    return form_ref


def _remember_form(
    db: Session,
    *,
    launch: CampaignLaunch,
    page: PageAccount,
    form_id: str,
    spec: LeadFormSpec,
    watch: LaunchTrace,
) -> None:
    """Record the form in leads, and never fail a launch over it."""
    from app.modules.leads.services import record_lead_form

    try:
        row = record_lead_form(
            db,
            owner=launch.owner,
            page=page,
            provider=launch.provider,
            external_id=form_id,
            name=spec.name,
            questions=questions_for(spec.questions),
            privacy_policy_url=spec.privacy_policy_url,
            locale=spec.locale,
            ending=_ending(spec),
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("lead form not recorded", extra={"form": form_id})
        watch.note(f"LeadForm yozilmadi: {form_id}")
        return
    watch.db(
        "LeadForm",
        {
            "external_id": ("", row.external_id),
            "status": ("", row.status),
            "questions_raw": ("", row.questions_raw),
        },
    )


def _ending(spec: LeadFormSpec) -> dict[str, str]:
    button = spec.thank_you_type
    if button == THANK_YOU_WEBSITE:
        kind, target = "website", spec.thank_you_url
    elif button == THANK_YOU_CALL:
        kind, target = "call", spec.thank_you_phone
    elif button == THANK_YOU_NONE:
        kind, target = "none", ""
    else:
        kind, target = "other", ""
    text = spec.thank_you_button_text if kind != "none" else ""
    return {"kind": kind, "target": target, "button_text": text}


# -- the campaign a page's goal shares -------------------------------------------------


@contextmanager
def campaign_for(
    db: Session,
    *,
    launch: CampaignLaunch,
    account: AdAccount,
    page: PageAccount,
    goal: str,
    objective: str,
    token: str,
    dry_run: bool,
    spec_for: SpecFor,
    make: MakeCampaign,
    watch: LaunchTrace,
) -> Iterator[ExternalRef]:
    """The campaign this launch's ad group goes into, held until it is in."""
    from app.modules.ads.services.removal import goal_lock

    with goal_lock(account_id=str(account.id), page_id=str(page.id), goal=goal):
        row = _own(
            db, launch=launch, token=token, dry_run=dry_run, watch=watch
        ) or _opened(
            db,
            launch=launch,
            account=account,
            page=page,
            goal=goal,
            objective=objective,
        )
        launch.goal_campaign_id = row.id
        db.commit()
        if not row.external_id:
            _make(db, launch=launch, row=row, spec_for=spec_for, make=make, watch=watch)
        watch.decision(
            "kampaniya",
            {"goal_campaign": str(row.id), "number": row.number, "id": row.external_id},
        )
        yield ExternalRef(
            provider=ProviderName(launch.provider), level="campaign", id=row.external_id
        )


def _own(
    db: Session,
    *,
    launch: CampaignLaunch,
    token: str,
    dry_run: bool,
    watch: LaunchTrace,
) -> GoalCampaign | None:
    row = launch.goal_campaign
    if row is None or row.retired_at is not None:
        return None
    if not row.external_id:
        return row
    held = _held(db, row=row, launch=launch, token=token, dry_run=dry_run)
    watch.decision(
        f"kampaniya #{row.number}", {"id": row.external_id, "guruhlar": held}
    )
    if held == GONE:
        row.retired_at = utcnow()
        db.commit()
        return None
    return row


def _held(
    db: Session, *, row: GoalCampaign, launch: CampaignLaunch, token: str, dry_run: bool
) -> int | Unusable:
    from app.modules.ads.selectors.launched import ever_switched_on
    from app.modules.metrics.selectors.facts import campaign_has_run

    if dry_run or is_dry_run_id(row.external_id):
        return int(
            db.scalar(
                select(func.count(CampaignLaunch.id)).where(
                    CampaignLaunch.owner_id == row.owner_id,
                    CampaignLaunch.goal_campaign_id == row.id,
                    CampaignLaunch.status == str(LaunchStatus.CREATED),
                )
            )
            or 0
        )
    ref = ExternalRef(
        provider=ProviderName(row.provider), level="campaign", id=row.external_id
    )
    port = registry.get(row.provider).campaigns
    try:
        status = port.get_status(ref=ref, token=token)
    except NotFound:
        return GONE
    if status.delivery == "finished":
        return GONE
    # A rollback that failed left it behind holding what an older attempt asked.
    if (status.daily_budget_minor or None) != campaign_budget_minor(launch=launch):
        return GONE
    if status.delivery == "paused" and (
        ever_switched_on(db, row=row)
        or campaign_has_run(db, owner=row.owner, campaign_id=row.external_id)
    ):
        return STOPPED
    return port.count_adsets(campaign=ref, token=token)


def _opened(
    db: Session,
    *,
    launch: CampaignLaunch,
    account: AdAccount,
    page: PageAccount,
    goal: str,
    objective: str,
) -> GoalCampaign:
    last = db.scalar(
        select(func.max(GoalCampaign.number)).where(
            GoalCampaign.owner_id == launch.owner_id,
            GoalCampaign.ad_account_id == account.id,
            GoalCampaign.page_id == page.id,
            GoalCampaign.goal == goal,
        )
    )
    row = GoalCampaign(
        owner_id=launch.owner_id,
        provider=launch.provider,
        ad_account_id=account.id,
        page_id=page.id,
        goal=goal,
        objective_raw=objective,
        number=int(last or 0) + 1,
    )
    db.add(row)
    db.commit()
    return row


def _make(
    db: Session,
    *,
    launch: CampaignLaunch,
    row: GoalCampaign,
    spec_for: SpecFor,
    make: MakeCampaign,
    watch: LaunchTrace,
) -> None:
    spec = spec_for(row.number)
    watch.inputs("spec", spec.model_dump())
    try:
        ref = make(spec)
    except ProviderError:
        found = ref_field.first_id(launch.created_refs or {}, LaunchStep.CAMPAIGN)
        if found:
            row.external_id = found
            db.commit()
        raise
    row.external_id = ref.id
    db.commit()
