"""Reading preparations and the interest cache."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

from metaads.accounts import billing_url, manager_url
from metaads.leadforms import terms_url
from metaads.writing import is_dry_run_id
from sqlalchemy import ColumnElement, or_, select, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.common.presets import default_provider
from app.modules.accounts.models import User
from app.modules.ads import draft as draft_field
from app.modules.ads import geo as geo_field
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import (
    HARMLESS_STEPS,
    ROLLBACK_ORDER,
    STRANDED_SWEEP_BATCH,
    STRANDED_SWEEP_COOLDOWN_MINUTES,
    STRANDED_SWEEP_DAYS,
    UNCHANGED_REFUSALS,
    ChatChannel,
    DraftSection,
    LaunchStatus,
    LaunchStep,
    MediaKind,
)
from app.modules.ads.models import CampaignLaunch, InterestTerm, LaunchCreative
from app.modules.ads.selectors.ad_groups import underfunded
from app.modules.ads.selectors.attempts import reaches_nobody, repeats_refusal
from app.modules.ads.selectors.copy_notes import destination_phone, missing_copy
from app.modules.ads.selectors.goals import (
    chosen_channel,
    destination_link,
    goal_optimization,
    goal_preset,
)
from app.modules.ads.selectors.launch_page import launch_page
from app.modules.ads.selectors.variants import launch_variants
from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
from app.modules.integrations.models import AdAccount, PageAccount
from core.targeting import daily_floor

LAUNCH_GEO_LOOKBACK: Final = 5
OPEN_STATUSES = (
    LaunchStatus.DRAFT,
    LaunchStatus.BUILDING,
    LaunchStatus.READY,
    LaunchStatus.FAILED,
    LaunchStatus.ROLLED_BACK,
)
RESUME_STEPS: Final = (("goal", "plan"), ("daily_budget_minor", "plan"))
MEDIA_STEP: Final = "media"
REVIEW_STEP: Final = "review"
REQUIRED_ANSWERS: Final = ("goal", "daily_budget_minor")


def _open() -> list[str]:
    return [str(status) for status in OPEN_STATUSES]


def provider_for(db: Session, *, owner: User) -> str:
    """Whose catalogue and whose adapter this owner's campaign is built for."""
    from app.modules.integrations.selectors import active_ad_account

    account = active_ad_account(db, owner=owner)
    return account.provider if account is not None else default_provider()


def launch_for(db: Session, *, owner: User, launch_id: UUID) -> CampaignLaunch | None:
    """One preparation, or ``None`` when it is not this owner's."""
    return db.scalar(
        select(CampaignLaunch).where(
            CampaignLaunch.owner_id == owner.id, CampaignLaunch.id == launch_id
        )
    )


def open_launch(
    db: Session,
    *,
    owner: User,
    page: PageAccount | None,
    ad_account: AdAccount | None,
) -> CampaignLaunch | None:
    """The newest preparation still worth resuming, on one page and one account."""
    if ad_account is None:
        return None
    here = (
        CampaignLaunch.page_id.is_(None)
        if page is None
        else or_(CampaignLaunch.page_id == page.id, CampaignLaunch.page_id.is_(None))
    )
    return db.scalar(
        select(CampaignLaunch)
        .where(
            CampaignLaunch.owner_id == owner.id,
            CampaignLaunch.status.in_(_open()),
            CampaignLaunch.ad_account_id == ad_account.id,
            here,
        )
        .order_by(CampaignLaunch.created_at.desc())
        .limit(1)
    )


def refused_launch(
    db: Session, *, owner: User, page: PageAccount | None = None
) -> CampaignLaunch | None:
    """The newest open preparation that went wrong."""
    query = select(CampaignLaunch).where(
        CampaignLaunch.owner_id == owner.id,
        CampaignLaunch.status.in_(_open()),
        or_(
            CampaignLaunch.status.in_(
                [str(LaunchStatus.FAILED), str(LaunchStatus.ROLLED_BACK)]
            ),
            CampaignLaunch.error_code != "",
        ),
    )
    if page is not None:
        query = query.where(
            or_(CampaignLaunch.page_id == page.id, CampaignLaunch.page_id.is_(None))
        )
    return db.scalar(query.order_by(CampaignLaunch.created_at.desc()).limit(1))


def last_geo(
    db: Session,
    *,
    owner: User,
    page: PageAccount | None = None,
    before: UUID | None = None,
) -> dict[str, Any] | None:
    """The geography this page last chose, or nothing if it never has."""
    query = select(CampaignLaunch.draft).where(CampaignLaunch.owner_id == owner.id)
    if page is not None:
        query = query.where(CampaignLaunch.page_id == page.id)
    if before is not None:
        query = query.where(CampaignLaunch.id != before)
    rows = db.scalars(
        query.order_by(CampaignLaunch.created_at.desc()).limit(LAUNCH_GEO_LOOKBACK)
    )
    for draft in rows:
        chosen = draft_field.chosen(draft or {}, DraftSection.AUDIENCE)
        if isinstance(chosen, dict) and geo_field.origin_of(chosen) == "chosen":
            return chosen
    return None


def last_daily_budget(db: Session, *, launch: CampaignLaunch) -> int:
    """What this account last agreed to spend a day, or nought if never."""
    found = db.scalar(
        select(CampaignLaunch.daily_budget_minor)
        .where(
            CampaignLaunch.owner_id == launch.owner_id,
            CampaignLaunch.ad_account_id == launch.ad_account_id,
            CampaignLaunch.daily_budget_minor > 0,
            CampaignLaunch.id != launch.id,
        )
        .order_by(CampaignLaunch.created_at.desc())
        .limit(1)
    )
    return int(found or 0)


def resume_step(launch: CampaignLaunch) -> str:
    """The step this preparation stopped on: ``plan``, ``media`` or ``review``."""
    if launch.status != LaunchStatus.DRAFT:
        return REVIEW_STEP
    for key, step in RESUME_STEPS:
        if not (launch.answers or {}).get(key):
            return step
    return MEDIA_STEP


def known_terms(
    db: Session, *, owner: User, provider: str, queries: list[str]
) -> dict[str, InterestTerm]:
    if not queries:
        return {}
    rows = db.scalars(
        select(InterestTerm).where(
            InterestTerm.owner_id == owner.id,
            InterestTerm.provider == provider,
            InterestTerm.query.in_(queries),
        )
    )
    return {row.query: row for row in rows}


def page_terms_url(db: Session, *, launch: CampaignLaunch) -> str:
    page = launch_page(db, launch=launch)
    return terms_url(page.external_id) if page else ""


def ads_manager_url(*, launch: CampaignLaunch) -> str:
    return manager_url(launch.ad_account.external_id)


def launch_billing_url(*, launch: CampaignLaunch) -> str:
    return billing_url(launch.ad_account.external_id)


@dataclass(frozen=True, slots=True)
class IdentityHold:
    person: str
    repeated: bool


def identity_hold(*, launch: CampaignLaunch) -> IdentityHold:
    connection = launch.ad_account.connection
    return IdentityHold(
        person=connection.external_user_name,
        repeated=connection.action_refusals > 1,
    )


def answers_complete(*, launch: CampaignLaunch) -> bool:
    return all((launch.answers or {}).get(key) for key in REQUIRED_ANSWERS)


def _unusable(variant: LaunchCreative) -> bool:
    if not variant.media_asset_id:
        return not variant.media_upload
    asset = variant.media_asset
    return asset is None or asset.kind == MediaKind.POST or asset.is_eligible is False


def launch_blocker(db: Session, *, launch: CampaignLaunch) -> str:
    """Which precondition the create button would be refused on, or ``""``."""
    from app.modules.billing.selectors.subscription import may_prepare
    from app.modules.businesses.selectors import business_for_page
    from app.modules.integrations.selectors import missing_scopes
    from app.modules.leads.selectors.reads import collecting_form

    owner = launch.owner
    if not may_prepare(db, owner=owner):
        return "subscription"
    account = launch.ad_account
    if account.connection.status not in USABLE_CONNECTION_STATUSES:
        return "reconnect"
    page = launch_page(db, launch=launch)
    if page is None:
        return "no_page"
    if not page.is_active:
        return "page_gone"
    if missing_scopes(db, owner=owner):
        return "permissions"
    if geo_field.unresolved(draft_field.chosen(launch.draft, DraftSection.AUDIENCE)):
        return "places_missing"
    variants = launch_variants(db, launch=launch)
    if not variants:
        return "media_missing"
    if any(_unusable(variant) for variant in variants):
        return "media_gone"
    if missing_copy(db, launch=launch):
        return "copy_missing"
    preset = goal_preset(db, launch=launch)
    business = business_for_page(db, owner=owner, page=launch.page)
    if (
        preset is not None
        and preset.needs_link
        and (business is None or not destination_link(launch=launch, business=business))
    ):
        return "site_missing"
    if (
        preset is not None
        and preset.needs_phone
        and (
            business is None or not destination_phone(launch=launch, business=business)
        )
    ):
        return "phone_missing"
    chosen_form = launch.lead_form_external_id
    if (
        preset is not None
        and preset.needs_lead_form
        and chosen_form
        and not collecting_form(db, owner=owner, page=page, external_id=chosen_form)
    ):
        return "form_gone"
    if (
        chosen_channel(launch=launch) == ChatChannel.INSTAGRAM
        and not page.has_instagram
    ):
        return "chat_channel"
    if preset is not None and preset.opens_profile and not page.can_open_profile:
        return "instagram_profile"
    least = daily_floor(
        account_minor=account.min_daily_budget_minor,
        optimization_goal=goal_optimization(db, launch=launch),
    )
    if least and int(launch.daily_budget_minor or 0) < least:
        return "budget_low"
    if underfunded(db, launch=launch, floor_minor=least, variants=variants) is not None:
        return "group_budget_low"
    if reaches_nobody(launch=launch):
        return "reach_empty"
    if launch.error_code in UNCHANGED_REFUSALS and repeats_refusal(
        db,
        launch=launch,
        business=business,
        preset_version=preset.version if preset is not None else "",
    ):
        return "unchanged"
    return ""


def owns(db: Session, launch: CampaignLaunch, step: str) -> bool:
    """Whether the object recorded under ``step`` is this launch's to delete."""
    from app.modules.ads.selectors.launched import shares_campaign

    return not (step == LaunchStep.CAMPAIGN and shares_campaign(db, launch=launch))


def _real(launch: CampaignLaunch, step: str) -> bool:
    return any(
        not is_dry_run_id(external_id)
        for external_id in ref_field.ref_ids(launch.created_refs or {}, step)
    )


def removable_refs(db: Session, launch: CampaignLaunch) -> list[str]:
    """Steps a rollback would still try to delete for this launch."""
    return [
        step
        for step in ROLLBACK_ORDER
        if _real(launch, step) and owns(db, launch, step)
    ]


def stranded_refs(db: Session, launch: CampaignLaunch) -> list[str]:
    """Steps whose object is really out there and really blocks a next step."""
    return [
        step
        for step in launch.created_refs or {}
        if step not in HARMLESS_STEPS and _real(launch, step) and owns(db, launch, step)
    ]


def stranded_refs_of(launch: CampaignLaunch) -> list[str]:
    """``stranded_refs`` read through the launch's own session."""
    from sqlalchemy.orm import object_session

    db = object_session(launch)
    if db is None:
        return [
            step
            for step in launch.created_refs or {}
            if step not in HARMLESS_STEPS and _real(launch, step)
        ]
    return stranded_refs(db, launch)


def stranded_launches(db: Session, *, now: datetime) -> list[CampaignLaunch]:
    """Failed launches that still have objects at the provider."""
    return list(
        db.scalars(
            select(CampaignLaunch)
            .where(
                CampaignLaunch.status == str(LaunchStatus.FAILED),
                or_(*(_has_ref(step) for step in ROLLBACK_ORDER)),
                CampaignLaunch.finished_at >= now - timedelta(days=STRANDED_SWEEP_DAYS),
                CampaignLaunch.updated_at
                <= now - timedelta(minutes=STRANDED_SWEEP_COOLDOWN_MINUTES),
            )
            .order_by(CampaignLaunch.finished_at)
            .limit(STRANDED_SWEEP_BATCH)
        )
    )


def _has_ref(step: str) -> ColumnElement[bool]:
    return type_coerce(CampaignLaunch.created_refs, JSONB).has_key(str(step))
