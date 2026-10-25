"""Every setting one edit dialog changed, sent on its way in one call; and fetching an advert's preview."""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from adskit import ExternalRef, registry
from adskit.errors import ProviderError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.exceptions import DomainError
from app.modules.accounts.models import User
from app.modules.ads.constants import PREVIEW_AD_FORMAT, EditSection, ManagedLevel
from app.modules.ads.exceptions import ChangeRefused, PreviewUnavailable, UnknownTarget
from app.modules.ads.models import AdPreview
from app.modules.ads.selectors.editable import Editable
from core.targeting import AudienceEdit, changed, revise
from core.targeting.exceptions import TargetingError

logger = logging.getLogger(__name__)

BOTH_HALVES = "Tugash sanasi yuborildi, chegara esa yo'q: %(refusal)s"


@dataclass(frozen=True, slots=True)
class SettingsOutcome:
    """What became of each section of one press."""

    queued: tuple[str, ...] = ()
    refused: dict[str, str] = field(default_factory=dict)

    @property
    def all_landed(self) -> bool:
        return not self.refused


def change_settings(
    db: Session,
    *,
    user: User,
    editable: Editable,
    daily_budget_minor: int | None = None,
    audience: AudienceEdit | None = None,
    end_time: datetime | None = None,
    spend_cap_minor: int | None = None,
) -> SettingsOutcome:
    """Ask for every section that actually moved, and say what came of each."""
    queued: list[str] = []
    refused: dict[str, str] = {}
    attempts = (
        (
            EditSection.BUDGET,
            _budget(db, user=user, editable=editable, wanted=daily_budget_minor),
        ),
        (
            EditSection.AUDIENCE,
            _audience(db, user=user, editable=editable, wanted=audience),
        ),
        (
            EditSection.LIMITS,
            _limits(
                db,
                user=user,
                editable=editable,
                end_time=end_time,
                spend_cap_minor=spend_cap_minor,
            ),
        ),
    )
    for section, outcome in attempts:
        if outcome is None:
            continue
        if outcome:
            refused[str(section)] = outcome
        else:
            queued.append(str(section))
    return SettingsOutcome(queued=tuple(queued), refused=refused)


def _budget(
    db: Session, *, user: User, editable: Editable, wanted: int | None
) -> str | None:
    from app.modules.ads.services.manage import request_budget

    target = editable.budget
    if target is None or wanted is None or wanted == target.controls.daily_budget_minor:
        return None
    try:
        with db.begin_nested():
            request_budget(
                db,
                user=user,
                level=target.level,
                external_id=target.external_id,
                daily_budget_minor=wanted,
            )
    except DomainError as exc:
        return str(exc)
    return ""


def _audience(
    db: Session, *, user: User, editable: Editable, wanted: AudienceEdit | None
) -> str | None:
    from app.modules.ads.selectors.actions import managed_target
    from app.modules.ads.services.manage import request_targeting

    target = editable.audience
    if target is None or wanted is None or wanted.is_empty:
        return None
    row = managed_target(
        db, owner=user, level=ManagedLevel.ADSET, external_id=target.external_id
    )
    if row is None:
        return str(UnknownTarget())
    stored = getattr(row, "targeting_raw", None) or {}
    try:
        if not changed(stored, edit=wanted):
            return None
        revised = revise(stored, edit=wanted)
    except TargetingError:
        return str(ChangeRefused())
    try:
        with db.begin_nested():
            request_targeting(
                db, user=user, external_id=target.external_id, targeting=revised
            )
    except DomainError as exc:
        return str(exc)
    return ""


def _limits(
    db: Session,
    *,
    user: User,
    editable: Editable,
    end_time: datetime | None,
    spend_cap_minor: int | None,
) -> str | None:
    from app.modules.ads.services.manage import request_end_time, request_spend_cap

    target = editable.limits
    if target is None:
        return None
    sent = False
    if end_time is not None and end_time != target.end_time:
        try:
            with db.begin_nested():
                request_end_time(
                    db,
                    user=user,
                    external_id=target.adset_external_id,
                    end_time=end_time,
                )
        except DomainError as exc:
            return str(exc)
        sent = True
    if spend_cap_minor is not None and spend_cap_minor != target.spend_cap_minor:
        try:
            with db.begin_nested():
                request_spend_cap(
                    db,
                    user=user,
                    external_id=target.campaign_external_id,
                    spend_cap_minor=spend_cap_minor,
                )
        except DomainError as exc:
            return BOTH_HALVES % {"refusal": str(exc)} if sent else str(exc)
        sent = True
    return "" if sent else None


def fetch_preview(
    db: Session, *, user: User, external_id: str, ad_format: str = PREVIEW_AD_FORMAT
) -> AdPreview:
    """Fetch and store the frame showing this advert on one surface."""
    from app.modules.ads.selectors.actions import account_of, managed_target
    from app.modules.ads.services.access import token_for

    target = managed_target(
        db, owner=user, level=ManagedLevel.AD, external_id=external_id
    )
    if target is None:
        raise UnknownTarget
    account = account_of(target=target, level=ManagedLevel.AD)
    token = token_for(ad_account=account)
    ref = ExternalRef(
        provider=target.provider, level=ManagedLevel.AD, id=str(target.external_id)
    )  # type: ignore[arg-type]
    try:
        preview = registry.get(target.provider).campaigns.get_preview(
            ref=ref, ad_format=ad_format, token=token
        )
    except ProviderError as exc:
        logger.info("no preview for %s at %s: %s", external_id, ad_format, exc.code)
        raise PreviewUnavailable from exc
    row = db.scalar(
        select(AdPreview).where(
            AdPreview.provider == target.provider,
            AdPreview.external_id == str(target.external_id),
            AdPreview.ad_format == ad_format,
        )
    )
    if row is None:
        row = AdPreview(
            provider=target.provider,
            external_id=str(target.external_id),
            ad_format=ad_format,
        )
        db.add(row)
    row.owner_id = user.id
    row.ad_account_id = account.id
    row.src = preview.src
    row.width = preview.width
    row.height = preview.height
    row.fetched_at = utcnow()
    db.flush()
    return row


__all__ = ["BOTH_HALVES", "SettingsOutcome", "change_settings", "fetch_preview"]
