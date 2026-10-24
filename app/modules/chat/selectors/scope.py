"""The edges an answer is drawn inside: the cabinet's clock, the subscription, and the page."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from metaads import PROVIDER as META
from sqlalchemy import ColumnElement, Select, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import NO_PAGE, PageScope
from app.modules.integrations.models import AdAccount, PageAccount


def lead_window(
    db: Session, *, owner: User, since: date, until: date
) -> tuple[datetime, datetime]:
    """The same window as two instants, on the cabinet's own clock."""
    from app.modules.integrations.selectors import active_ad_account

    account = active_ad_account(db, owner=owner)
    tzinfo = account.tzinfo() if account is not None else ZoneInfo("UTC")
    return (
        datetime.combine(since, time.min, tzinfo=tzinfo),
        datetime.combine(until, time.max, tzinfo=tzinfo),
    )


def subscribed_accounts(db: Session, *, owner: User) -> list[AdAccount]:
    """Meta's ad accounts in the subscription, the current one first."""
    return list(
        db.scalars(
            select(AdAccount)
            .where(
                AdAccount.owner_id == owner.id,
                AdAccount.provider == META,
                AdAccount.is_active.is_(True),
            )
            .order_by(AdAccount.is_current.desc(), AdAccount.name)
        )
    )


def subscribed_pages_query(owner: User) -> Select[tuple[PageAccount]]:
    return (
        select(PageAccount)
        .where(PageAccount.owner_id == owner.id, PageAccount.is_active.is_(True))
        .order_by(PageAccount.is_current.desc(), PageAccount.name)
    )


def subscribed_pages(db: Session, *, owner: User) -> list[PageAccount]:
    """The pages switched on in the subscription, the current one first."""
    return list(db.scalars(subscribed_pages_query(owner)))


def in_subscription(ad_account_id: ColumnElement) -> ColumnElement[bool]:  # type: ignore[type-arg]
    """Rows under an ad account this cabinet reads: switched on, unrecorded, or watched."""
    from app.modules.integrations.selectors.watch import observed

    return or_(
        ad_account_id.in_(
            select(AdAccount.id).where(
                AdAccount.is_active.is_(True), AdAccount.provider == META
            )
        ),
        ad_account_id.is_(None),
        ad_account_id.in_(select(AdAccount.id).where(observed())),
    )


def reads_ads_manager(db: Session, *, owner: User) -> bool:
    """Whether a look-up may describe advertising built in Ads Manager."""
    from app.modules.billing.selectors import live_subscription

    subscription = live_subscription(db, owner=owner)
    return subscription is not None and not subscription.plan.is_one_time


def current_page_scope(db: Session, *, owner: User) -> PageScope:
    """What the assistant may describe: this page, and what we built on it."""
    from app.modules.ads.selectors import all_launched_campaign_ids
    from app.modules.ads.selectors import current_page_scope as page_the_owner_is_on

    here = page_the_owner_is_on(db, owner=owner)
    return here.built_here(all_launched_campaign_ids(db, owner=owner))


def asked_scopes(db: Session, *, owner: User) -> tuple[PageScope, PageScope]:
    """``(described, counted)`` for one answer's look-ups."""
    from app.modules.ads.selectors import all_launched_campaign_ids
    from app.modules.ads.selectors import current_page_scope as page_the_owner_is_on

    here = page_the_owner_is_on(db, owner=owner)
    counted = here.built_here(all_launched_campaign_ids(db, owner=owner))
    if not reads_ads_manager(db, owner=owner):
        return counted, counted
    return here.marking(counted), counted


__all__ = [
    "NO_PAGE",
    "PageScope",
    "asked_scopes",
    "current_page_scope",
    "in_subscription",
    "lead_window",
    "reads_ads_manager",
    "subscribed_accounts",
    "subscribed_pages",
    "subscribed_pages_query",
]
