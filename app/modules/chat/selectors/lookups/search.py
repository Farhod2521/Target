"""Finding a thing the person named, or whose id they pasted."""

from datetime import datetime
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.chat.selectors.briefs import delivery_label
from app.modules.chat.selectors.lookups.common import (
    BUILT_IN_ADS_MANAGER,
    in_subscription,
    named,
    origin,
    section,
)
from app.modules.chat.selectors.scope import subscribed_pages_query
from app.modules.integrations.models import AdAccount, PageAccount
from app.modules.leads.constants import LeadFormStatus
from app.modules.leads.models import LeadForm
from core.chat.lookups import FOUND_ROWS, Search

NOT_PAID = "NOT in this subscription, nothing about it is available here"
OTHER_PAGE = "on another page of this subscription - the owner switches to that page to ask about it"


def find(
    db: Session, *, owner: User, arguments: Search, scope: PageScope, now: datetime
) -> str:
    """Everything whose name holds the query, or whose id is the query."""
    text = arguments.query.strip()
    rows = [
        *_accounts(db, owner=owner, text=text),
        *_pages(db, owner=owner, text=text, scope=scope),
        *_campaigns(db, owner=owner, text=text, scope=scope),
        *_groups(db, owner=owner, text=text, scope=scope),
        *_adverts(db, owner=owner, text=text, scope=scope),
        *_forms(db, owner=owner, text=text, scope=scope),
    ][:FOUND_ROWS]
    return "\n".join(
        section(f"Found for {text!r}", rows, empty="nothing with that name or id")
    )


def _matching(db: Session, query: Select[Any], model: Any, text: str) -> list[Any]:
    """By id, whole - or by name, in part."""
    return list(
        db.scalars(
            query.where(
                or_(model.external_id == text, model.name.ilike(f"%{text}%"))
            ).limit(FOUND_ROWS)
        )
    )


def _accounts(db: Session, *, owner: User, text: str) -> list[str]:
    from metaads import PROVIDER as META

    query = (
        select(AdAccount)
        .where(
            AdAccount.owner_id == owner.id,
            AdAccount.provider == META,
            AdAccount.is_active.is_(True),
        )
        .order_by(AdAccount.is_current.desc(), AdAccount.name)
    )
    return [
        f"- ad account {named(row.name, row.external_id)} (id {row.external_id})"
        for row in _matching(db, query, AdAccount, text)
    ]


def _pages(db: Session, *, owner: User, text: str, scope: PageScope) -> list[str]:
    inside = [
        f"- Facebook page {named(row.name, row.external_id)} (id {row.external_id})"
        + ("" if scope.allows_page(row.external_id) else f" - {OTHER_PAGE}")
        for row in _matching(db, subscribed_pages_query(owner), PageAccount, text)
    ]
    left_out = [
        f"- Facebook page {named(row.name, row.external_id)} (id {row.external_id}) - {NOT_PAID}"
        for row in _matching(
            db,
            select(PageAccount)
            .where(PageAccount.owner_id == owner.id, PageAccount.is_active.is_(False))
            .order_by(PageAccount.name),
            PageAccount,
            text,
        )
    ]
    return inside + left_out


def _campaigns(db: Session, *, owner: User, text: str, scope: PageScope) -> list[str]:
    query = (
        select(Campaign)
        .where(Campaign.owner_id == owner.id, in_subscription(Campaign.ad_account_id))
        .order_by(Campaign.created_time.desc(), Campaign.name)
    )
    return [
        f"- campaign {named(row.name, row.external_id)} (id {row.external_id}) - "
        + (
            str(delivery_label(row.delivery))
            + origin(scope, level="campaign", external_id=row.external_id)
            if scope.allows_campaign(row.external_id)
            else _not_here(scope, level="campaign", external_id=row.external_id)
        )
        for row in _matching(db, query, Campaign, text)
    ]


def _groups(db: Session, *, owner: User, text: str, scope: PageScope) -> list[str]:
    query = (
        select(AdSet)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .where(AdSet.owner_id == owner.id, in_subscription(Campaign.ad_account_id))
    )
    return [
        f"- ad group {named(row.name, row.external_id)} (id {row.external_id}) "
        f"in campaign {named(row.campaign.name, row.campaign.external_id)} - "
        + (
            str(delivery_label(row.delivery))
            + origin(scope, level="adset", external_id=row.external_id)
            if scope.allows_adset(row.external_id)
            else _not_here(scope, level="adset", external_id=row.external_id)
        )
        for row in _matching(db, query, AdSet, text)
    ]


def _adverts(db: Session, *, owner: User, text: str, scope: PageScope) -> list[str]:
    query = (
        select(Ad)
        .join(AdSet, AdSet.id == Ad.adset_id)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .where(Ad.owner_id == owner.id, in_subscription(Campaign.ad_account_id))
        .order_by(Ad.name)
    )
    return [
        f"- advert {named(row.name, row.external_id)} (id {row.external_id}) "
        f"in ad group {named(row.adset.name, row.adset.external_id)}, campaign "
        f"{named(row.adset.campaign.name, row.adset.campaign.external_id)} - "
        + (
            str(delivery_label(row.delivery))
            + origin(scope, level="adset", external_id=row.adset.external_id)
            if scope.allows_adset(row.adset.external_id)
            else _not_here(scope, level="adset", external_id=row.adset.external_id)
        )
        for row in _matching(db, query, Ad, text)
    ]


def _not_here(scope: PageScope, *, level: str, external_id: str) -> str:
    if scope.was_built_elsewhere(level=level, external_id=external_id):
        return f"{BUILT_IN_ADS_MANAGER} - not on the owner's current plan"
    on_other = scope.on_other_page(level=level, external_id=external_id)
    return OTHER_PAGE if on_other else NOT_PAID


def _status(value: str) -> str:
    try:
        return str(LeadFormStatus(value).label)
    except ValueError:
        return value


def _forms(db: Session, *, owner: User, text: str, scope: PageScope) -> list[str]:
    query = (
        select(LeadForm)
        .join(PageAccount, PageAccount.id == LeadForm.page_id)
        .where(LeadForm.owner_id == owner.id, PageAccount.is_active.is_(True))
        .order_by(LeadForm.created_time.desc(), LeadForm.created_at.desc(), LeadForm.id)
    )
    return [
        f"- lead form {named(row.name, row.external_id)} (id {row.external_id}) "
        f"on page {named(row.page.name, row.page.external_id)} - "
        + (
            _status(row.status)
            if scope.allows_page(row.page.external_id)
            else OTHER_PAGE
        )
        for row in _matching(db, query, LeadForm, text)
    ]


__all__ = ["find"]
