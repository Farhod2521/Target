"""Undoing a creation that stopped halfway, finishing the rollbacks nothing else
will finish, freeing stalled preparations, and taking withdrawn options out."""

import logging
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

from adskit.dto import RetiredOptionDTO
from adskit.errors import ProviderError
from adskit.refs import ExternalRef, Level, ProviderName
from metaads.launcher import MetaLauncher
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import utcnow
from app.common.exceptions import DomainError
from app.modules.accounts.models import User
from app.modules.ads import draft as draft_field
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import (
    HARMLESS_STEPS,
    LAUNCH_RELATED_TYPE,
    ROLLBACK_ORDER,
    STALLED_AFTER_MINUTES,
    DraftSection,
    LaunchStatus,
    LaunchStep,
)
from app.modules.ads.models import CampaignLaunch, InterestTerm
from app.modules.ads.rows import fresh
from app.modules.ads.selectors.launches import owns, removable_refs, stranded_launches
from app.modules.audit.constants import EventName
from app.modules.businesses.models import Business

logger = logging.getLogger(__name__)
_LEVELS: Final[dict[str, Level]] = {
    LaunchStep.FORM: "form",
    LaunchStep.CAMPAIGN: "campaign",
    LaunchStep.ADSET: "adset",
    LaunchStep.CREATIVE: "creative",
    LaunchStep.AD: "ad",
}
WORKING_STATUSES = (str(LaunchStatus.BUILDING), str(LaunchStatus.CREATING))
STALLED_CODE = "stalled"
RETIRED_SECTIONS = (DraftSection.INTERESTS, DraftSection.TRAITS)


def rollback_launch(
    db: Session, *, launch: CampaignLaunch, token: str, page_token: str, dry_run: bool
) -> int:
    """Delete everything this launch created. Returns how many went."""
    launcher = MetaLauncher()
    provider = ProviderName(launch.provider)
    removed = _sweep(
        db,
        launcher=launcher,
        launch=launch,
        provider=provider,
        token=token,
        page_token=page_token,
        dry_run=dry_run,
        attempt=1,
    )
    if removable_refs(db, launch):
        removed += _sweep(
            db,
            launcher=launcher,
            launch=launch,
            provider=provider,
            token=token,
            page_token=page_token,
            dry_run=dry_run,
            attempt=2,
        )
    _record(db, launch=launch, removed=removed)
    return removed


def _left_behind(db: Session, launch: CampaignLaunch) -> list[str]:
    return [
        step
        for step in launch.created_refs or {}
        if step not in HARMLESS_STEPS and owns(db, launch, step)
    ]


def _sweep(
    db: Session,
    *,
    launcher: MetaLauncher,
    launch: CampaignLaunch,
    provider: ProviderName,
    token: str,
    page_token: str,
    dry_run: bool,
    attempt: int,
) -> int:
    removed = 0
    for step in ROLLBACK_ORDER:
        if not owns(db, launch, step):
            continue
        for external_id in ref_field.ref_ids(launch.created_refs or {}, step):
            ref = ExternalRef(provider=provider, level=_LEVELS[step], id=external_id)
            secret = page_token if step == LaunchStep.FORM else token
            try:
                launcher.remove(ref=ref, token=secret, dry_run=dry_run)
            except ProviderError:
                logger.exception(
                    "rollback of %s failed at %s (%s) on attempt %s",
                    launch.id,
                    step,
                    ref,
                    attempt,
                )
                continue
            ref_field.clear(fresh(launch, "created_refs"), step, external_id)
            db.commit()
            removed += 1
    return removed


def _record(db: Session, *, launch: CampaignLaunch, removed: int) -> None:
    """Write down what is left, and say which of the two states this is."""
    from app.modules.ads.services.preflight import revert_log
    from app.modules.audit.services import emit

    refs = fresh(launch, "created_refs")
    if not owns(db, launch, LaunchStep.CAMPAIGN) and not ref_field.ref_ids(
        refs, LaunchStep.ADSET
    ):
        refs.pop(LaunchStep.CAMPAIGN, None)
    clean = not _left_behind(db, launch)
    launch.status = str(LaunchStatus.ROLLED_BACK if clean else LaunchStatus.FAILED)
    launch.progress = 0
    launch.finished_at = utcnow()
    revert_log(db, launch=launch)
    emit(
        db,
        owner_id=launch.owner_id,
        name=EventName.LAUNCH_ROLLED_BACK,
        aggregate_type=LAUNCH_RELATED_TYPE,
        aggregate_id=launch.id,
        payload={
            "removed": removed,
            "remaining": sorted(launch.created_refs or {}),
            "provider": launch.provider,
        },
    )
    db.commit()
    if not clean:
        logger.error(
            "rollback of %s left objects behind: %s",
            launch.id,
            sorted(launch.created_refs),
        )


# -- the sweeps ------------------------------------------------------------------------


def sweep_stranded_launches(db: Session, *, now: datetime) -> int:
    """Fan one rollback out per launch still holding objects. Returns how many."""
    from app.modules.ads.tasks import rollback_stranded_launch_task

    ids = [str(row.id) for row in stranded_launches(db, now=now)]
    for launch_id in ids:
        rollback_stranded_launch_task.delay(launch_id)
    if ids:
        logger.info("%s stranded launches queued for another rollback", len(ids))
    return len(ids)


def rollback_stranded_launch(db: Session, *, launch_id: str) -> str:
    """Ask again for one launch's leftovers. Returns a word for the log."""
    from app.modules.ads.services.access import (
        launch_account_and_token,
        launch_page_token,
    )

    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if launch is None:
        return "gone"
    if not removable_refs(db, launch):
        return "clean"
    try:
        _account, token = launch_account_and_token(db, launch=launch)
        page_token = launch_page_token(db, launch=launch)
    except DomainError as exc:
        logger.info("launch %s cannot be cleaned up yet: %s", launch.id, exc)
        return "unusable"
    removed = rollback_launch(
        db,
        launch=launch,
        token=token,
        page_token=page_token,
        dry_run=bool(settings.ads_dry_run),
    )
    return f"removed:{removed}"


def release_stalled_launches(db: Session) -> int:
    """Mark long-running preparations failed. Returns how many."""
    now = utcnow()
    cutoff = now - timedelta(minutes=STALLED_AFTER_MINUTES)
    stalled = (
        CampaignLaunch.status.in_(WORKING_STATUSES),
        or_(
            CampaignLaunch.started_at < cutoff,
            and_(
                CampaignLaunch.started_at.is_(None), CampaignLaunch.updated_at < cutoff
            ),
        ),
    )
    frozen = db.execute(
        select(CampaignLaunch.id, CampaignLaunch.status, CampaignLaunch.step).where(
            *stalled
        )
    ).all()
    if not frozen:
        return 0
    released = db.execute(
        update(CampaignLaunch)
        .where(*stalled)
        .values(
            status=str(LaunchStatus.FAILED),
            error_code=STALLED_CODE,
            progress=0,
            finished_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    for pk, status, step in frozen:
        logger.warning(
            "launch_stalled", extra={"launch": str(pk), "was": status, "step": step}
        )
    return int(released or 0)


# -- withdrawn options -----------------------------------------------------------------


def retire_options(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    retired: tuple[RetiredOptionDTO, ...],
) -> list[dict[str, str]]:
    """Replace or drop every withdrawn option. Returns what it changed."""
    from app.modules.ads.services.targeting import rebuild_targeting

    by_id = {option.retired_id: option for option in retired if option.retired_id}
    if not by_id:
        return []
    applied: list[dict[str, str]] = []
    draft = fresh(launch, "draft")
    for section in RETIRED_SECTIONS:
        chosen = draft_field.chosen(draft, section)
        if not isinstance(chosen, list):
            continue
        kept, changed = _swept(chosen, by_id)
        if changed:
            draft_field.choose(draft, section, kept)
            applied += changed
    if not applied:
        db.rollback()
        return []
    _forget(db, owner=launch.owner, options=by_id.values())
    rebuild_targeting(db, launch=launch, business=business)
    db.commit()
    return applied


def _swept(
    chosen: list[Any], by_id: dict[str, RetiredOptionDTO]
) -> tuple[list[Any], list[dict[str, str]]]:
    kept: list[Any] = []
    changed: list[dict[str, str]] = []
    for row in chosen:
        held = str(row.get("external_id", "")) if isinstance(row, dict) else ""
        option = by_id.get(held) if held else None
        if option is None:
            kept.append(row)
            continue
        was = str(row.get("label", "")) or option.retired_name
        if not option.alternative_id:
            changed.append({"was": was, "now": ""})
            continue
        row = dict(row)
        row["external_id"] = option.alternative_id
        row["label"] = option.alternative_name or was
        row["query"] = option.alternative_name or str(row.get("query", ""))
        kept.append(row)
        changed.append({"was": was, "now": str(row["label"])})
    return kept, changed


def _forget(db: Session, *, owner: User, options: Any) -> None:
    for option in options:
        query = update(InterestTerm).where(
            InterestTerm.owner_id == owner.id,
            InterestTerm.external_id == option.retired_id,
        )
        try:
            with db.begin_nested():
                if option.alternative_id:
                    db.execute(query.values(external_id=option.alternative_id))
                else:
                    db.execute(query.values(external_id="", confirmed_at=None))
        except SQLAlchemyError:
            logger.exception("term cache not corrected for %s", option.retired_id)
