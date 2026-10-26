"""What is asked of the provider before anything is written, the audit row a
launch leaves behind, and the nightly look at the pages adverts send people to."""

import hashlib
import logging
import uuid
from datetime import datetime
from time import monotonic
from typing import Any

from sitekit import SiteProbe, probe
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import (
    LAUNCH_LOG_PREFIX,
    SITE_CHECK_BUDGET_SECONDS,
    ChatChannel,
)
from app.modules.ads.exceptions import (
    AdAccountPaymentDue,
    AdAccountUnavailable,
    ChatChannelUnavailable,
    ConnectionUnusable,
    InstagramProfileUnavailable,
    PageRoleMissing,
    PageTermsNotAccepted,
    PermissionsMissing,
    UnknownLeadForm,
)
from app.modules.ads.models import CampaignLaunch, SiteCheck
from app.modules.ads.selectors.goals import chosen_channel, goal_preset
from app.modules.audit.constants import ActionStatus, ActionType, ActorType
from app.modules.audit.models import ActionLog
from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
from app.modules.integrations.models import AdAccount, PageAccount, ProviderConnection
from core.targeting import BuiltTargeting

logger = logging.getLogger(__name__)
TARGET_LEVEL = "adset"
KEY_PREFIX = LAUNCH_LOG_PREFIX
REFRESHED = (
    "url",
    "final_url",
    "outcome",
    "status_code",
    "meta_pixel_ids",
    "has_tag_manager",
    "is_down",
    "down_since",
    "checked_at",
    "updated_at",
)


# -- the preflight ---------------------------------------------------------------------


def preflight(db: Session, *, launch: CampaignLaunch) -> None:
    """Three reads and five checks. Raises the first thing that would fail."""
    from app.modules.ads.services.access import launch_page_for

    owner = launch.owner
    account = launch.ad_account
    page = launch_page_for(db, launch=launch)
    _refresh(db, account.connection)
    db.refresh(account)
    db.refresh(page)
    check_permissions(db, owner=owner)
    _check_account(account=account)
    _check_page(page=page, needs_lead_form=_makes_a_form(db, launch))
    _check_form(db, launch=launch, page=page)
    _check_channel(launch=launch, page=page)
    _check_profile(db, launch=launch, page=page)


def check_permissions(db: Session, *, owner: User) -> None:
    from app.modules.integrations.selectors import missing_scopes

    absent = missing_scopes(db, owner=owner)
    if absent:
        logger.warning("launch refused, missing scopes: %s", ", ".join(absent))
        raise PermissionsMissing(absent)


def _refresh(db: Session, connection: ProviderConnection) -> None:
    from app.modules.integrations.services.connect import verify_connection
    from app.modules.integrations.services.sync import sync_ad_accounts, sync_pages

    verify_connection(db, connection=connection)
    db.commit()
    db.refresh(connection)
    if connection.status not in USABLE_CONNECTION_STATUSES:
        raise ConnectionUnusable
    sync_ad_accounts(db, connection_id=connection.id)
    sync_pages(db, connection_id=connection.id)
    db.commit()


def _check_account(*, account: AdAccount) -> None:
    if account.may_advertise is False:
        if account.payment_due:
            raise AdAccountPaymentDue
        logger.warning(
            "launch refused, ad account %s status %s reason %s",
            account.external_id,
            account.account_status,
            account.disable_reason or "-",
        )
        raise AdAccountUnavailable


def _makes_a_form(db: Session, launch: CampaignLaunch) -> bool:
    preset = goal_preset(db, launch=launch)
    return preset is not None and preset.needs_lead_form


def _check_form(db: Session, *, launch: CampaignLaunch, page: PageAccount) -> None:
    from app.modules.leads.selectors.reads import collecting_form

    chosen = launch.lead_form_external_id
    if not chosen or not _makes_a_form(db, launch):
        return
    if collecting_form(db, owner=launch.owner, page=page, external_id=chosen) is None:
        logger.warning(
            "launch refused, form %s is not collecting on page %s",
            chosen,
            page.external_id,
        )
        raise UnknownLeadForm


def _check_channel(*, launch: CampaignLaunch, page: PageAccount) -> None:
    if chosen_channel(launch=launch) != ChatChannel.INSTAGRAM:
        return
    if not page.has_instagram:
        logger.warning(
            "launch refused, page %s has no instagram account", page.external_id
        )
        raise ChatChannelUnavailable


def _check_profile(db: Session, *, launch: CampaignLaunch, page: PageAccount) -> None:
    preset = goal_preset(db, launch=launch)
    if preset is None or not preset.opens_profile:
        return
    if not page.can_open_profile:
        logger.warning(
            "launch refused, page %s has no instagram profile", page.external_id
        )
        raise InstagramProfileUnavailable


def _check_page(*, page: PageAccount, needs_lead_form: bool) -> None:
    if page.may_advertise is False:
        raise PageRoleMissing(tuple(page.tasks or ()))
    if needs_lead_form and page.leadgen_terms_accepted is False:
        raise PageTermsNotAccepted


# -- the audit row ---------------------------------------------------------------------


def open_log(
    db: Session,
    *,
    launch: CampaignLaunch,
    account: AdAccount,
    built: BuiltTargeting,
    dry_run: bool,
) -> str:
    """Record the intention. Returns the row's id for the two closers."""
    row = ActionLog(
        owner_id=launch.owner_id,
        actor_type=str(ActorType.USER),
        actor_id=launch.owner_id,
        action=str(ActionType.CREATE_CAMPAIGN),
        target_provider=launch.provider,
        target_level=TARGET_LEVEL,
        target_external_id="",
        request_payload=_intent(launch=launch, account=account, built=built),
        previous_state={},
        status=str(ActionStatus.PENDING),
        dry_run=dry_run,
        idempotency_key=_key(db, launch),
    )
    db.add(row)
    db.commit()
    return str(row.id)


def close_log(db: Session, *, log_id: str, launch: CampaignLaunch) -> None:
    db.execute(
        update(ActionLog)
        .where(ActionLog.id == log_id)
        .values(
            status=str(ActionStatus.APPLIED),
            target_external_id=ref_field.first_id(
                launch.created_refs or {}, TARGET_LEVEL
            ),
            result_payload=dict(launch.created_refs or {}),
            dropped=dict(launch.dropped or {}),
            applied_at=utcnow(),
            updated_at=utcnow(),
        )
    )


def fail_log(db: Session, *, log_id: str, code: str, message: str) -> None:
    db.execute(
        update(ActionLog)
        .where(ActionLog.id == log_id)
        .values(
            status=str(ActionStatus.FAILED),
            error_code=code[:32],
            error_message=message,
            updated_at=utcnow(),
        )
    )
    db.commit()


def revert_log(db: Session, *, launch: CampaignLaunch) -> None:
    """Mark this launch's most recent attempt as undone."""
    latest = db.scalar(
        select(ActionLog)
        .where(ActionLog.idempotency_key.startswith(f"{KEY_PREFIX}:{launch.id}:"))
        .order_by(ActionLog.created_at.desc())
        .limit(1)
    )
    if latest is None:
        return
    latest.status = str(ActionStatus.REVERTED)
    latest.reverted_at = utcnow()
    latest.result_payload = dict(launch.created_refs or {})
    db.flush()


def _intent(
    *, launch: CampaignLaunch, account: AdAccount, built: BuiltTargeting
) -> dict[str, Any]:
    return {
        "account": account.external_id,
        "objective": built.objective,
        "optimization_goal": built.optimization_goal,
        "daily_budget_minor": launch.daily_budget_minor,
        "currency": launch.currency,
        "special_ad_categories": list(built.special_ad_categories),
        "special_ad_category_countries": list(built.special_ad_category_countries),
        "preset": f"{launch.preset_key}@{launch.preset_version}",
        "targeting": dict(launch.targeting or {}),
    }


def _key(db: Session, launch: CampaignLaunch) -> str:
    return f"{KEY_PREFIX}:{launch.id}:{attempt_number(db, launch)}"


def attempt_number(db: Session, launch: CampaignLaunch) -> int:
    prefix = f"{KEY_PREFIX}:{launch.id}:"
    return (
        int(
            db.scalar(
                select(func.count(ActionLog.id)).where(
                    ActionLog.idempotency_key.startswith(prefix)
                )
            )
            or 0
        )
        + 1
    )


# -- the pages adverts send people to ------------------------------------------------


def look_at_site(*, url: str) -> SiteProbe:
    """One look at ``url``. Never raises: every failure is an outcome."""
    return probe(url)


def digest_of(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def check_sites(db: Session, *, owner_id: str, now: datetime) -> int:
    """Look at every page this owner's delivering adverts link to."""
    from app.modules.ads.selectors.actions import live_landing_urls

    owner = db.get(User, uuid.UUID(str(owner_id)))
    if owner is None:
        return 0
    urls = live_landing_urls(db, owner=owner)
    started = monotonic()
    looks: list[tuple[str, SiteProbe]] = []
    for url in urls:
        if monotonic() - started >= SITE_CHECK_BUDGET_SECONDS:
            break
        looks.append((url, look_at_site(url=url)))
    if len(looks) < len(urls):
        logger.warning(
            "site look stopped at its time budget",
            extra={"owner_id": owner_id, "looked": len(looks), "pages": len(urls)},
        )
    _keep(db, owner=owner, live=urls, looks=looks, now=now)
    return len(looks)


def _keep(
    db: Session,
    *,
    owner: User,
    live: list[str],
    looks: list[tuple[str, SiteProbe]],
    now: datetime,
) -> None:
    down_before = dict(
        db.execute(
            select(SiteCheck.url_digest, SiteCheck.down_since).where(
                SiteCheck.owner_id == owner.id
            )
        )
        .tuples()
        .all()
    )
    rows = [
        {
            "id": uuid.uuid4(),
            "owner_id": owner.id,
            "url": url,
            "url_digest": digest_of(url),
            "final_url": look.final_url,
            "outcome": look.outcome,
            "status_code": look.status_code,
            "meta_pixel_ids": list(look.meta_pixel_ids),
            "has_tag_manager": look.has_tag_manager,
            "is_down": look.is_down,
            "down_since": (down_before.get(digest_of(url)) or now)
            if look.is_down
            else None,
            "checked_at": now,
            "created_at": now,
            "updated_at": now,
        }
        for url, look in looks
    ]
    if rows:
        statement = insert(SiteCheck).values(rows)
        db.execute(
            statement.on_conflict_do_update(
                index_elements=["owner_id", "url_digest"],
                set_={name: statement.excluded[name] for name in REFRESHED},
            )
        )
    db.execute(
        delete(SiteCheck).where(
            SiteCheck.owner_id == owner.id,
            SiteCheck.url_digest.not_in([digest_of(url) for url in live]),
        )
    )
    db.commit()
