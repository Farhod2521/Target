"""The owner's ad accounts, pages and subscription, and their audiences."""

from datetime import datetime

from metaads import PROVIDER as META
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.chat.selectors.lookups.common import (
    named,
    section,
    subscribed_accounts,
    subscribed_pages,
    window,
)
from app.modules.chat.selectors.scope import lead_window
from app.modules.chat.selectors.sections import audience_digests
from app.modules.integrations.models import AdAccount, PageAccount
from app.modules.leads.models import Lead, LeadForm
from core.chat.lookups import Nothing

PAGE_LEAD_DAYS = 30


def account_overview(
    db: Session, *, owner: User, arguments: Nothing, scope: PageScope, now: datetime
) -> str:
    """Accounts, pages, and what the subscription allows."""
    accounts = subscribed_accounts(db, owner=owner)
    every = subscribed_pages(db, owner=owner)
    pages = [page for page in every if scope.allows_page(page.external_id)]
    lines = section(
        "Ad accounts in the subscription",
        [_account_line(row) for row in accounts],
        empty="none switched on",
    )
    left_out = db.scalar(
        select(func.count(AdAccount.id)).where(
            AdAccount.owner_id == owner.id,
            AdAccount.provider == META,
            AdAccount.is_active.is_(False),
        )
    )
    if left_out:
        lines.append(f"- connected but not in the subscription: {left_out}")
    lines += ["", *_pages(db, owner=owner, pages=pages)]
    if len(every) > len(pages):
        lines.append(
            f"- other pages in the subscription: {len(every) - len(pages)} "
            "(the owner switches to one to ask about it)"
        )
    lines += ["", *_subscription(db, owner=owner, now=now, pages_on=len(every))]
    return "\n".join(lines)


def audiences(
    db: Session, *, owner: User, arguments: Nothing, scope: PageScope, now: datetime
) -> str:
    """Saved audiences, as the context would carry them."""
    rows = [
        f"- {item.name} - {item.kind}, size {item.size}, "
        f"{'ready' if item.is_ready else 'not ready'}"
        for item in audience_digests(db, owner=owner)
    ]
    return "\n".join(section("Saved audiences", rows, empty="none saved"))


def _account_line(row: AdAccount) -> str:
    parts = [f"currency {row.currency}"]
    if row.is_current:
        parts.insert(0, "current")
    if not row.may_advertise:
        parts.append("cannot advertise right now")
    if row.synced_at is not None:
        parts.append(f"figures synced {row.synced_at:%Y-%m-%d %H:%M} UTC")
    return f"- {named(row.name, row.external_id)} (id {row.external_id}): " + ", ".join(
        parts
    )


def _pages(db: Session, *, owner: User, pages: list[PageAccount]) -> list[str]:
    from app.modules.leads.selectors import priced

    ids = [page.id for page in pages]
    forms: dict[object, int] = {}
    leads: dict[object, int] = {}
    if ids:
        forms = dict(
            db.execute(
                select(LeadForm.page_id, func.count(LeadForm.id))
                .where(LeadForm.owner_id == owner.id, LeadForm.page_id.in_(ids))
                .group_by(LeadForm.page_id)
            ).all()
        )
        since, until = window(db, owner=owner, days=PAGE_LEAD_DAYS)
        start, end = lead_window(db, owner=owner, since=since, until=until)
        leads = dict(
            db.execute(
                select(LeadForm.page_id, func.count(Lead.id))
                .join(LeadForm, LeadForm.id == Lead.form_id)
                .where(
                    Lead.owner_id == owner.id,
                    Lead.is_test.is_(False),
                    priced(),
                    LeadForm.page_id.in_(ids),
                    Lead.submitted_at >= start,
                    Lead.submitted_at <= end,
                )
                .group_by(LeadForm.page_id)
            ).all()
        )
    rows = [
        _page_line(page, forms=forms.get(page.id, 0), leads=leads.get(page.id, 0))
        for page in pages
    ]
    lines = section("The Facebook page being asked about", rows, empty="none")
    left_out = db.scalar(
        select(func.count(PageAccount.id)).where(
            PageAccount.owner_id == owner.id, PageAccount.is_active.is_(False)
        )
    )
    if left_out:
        lines.append(f"- connected but not in the subscription: {left_out}")
    return lines


def _page_line(page: PageAccount, *, forms: int, leads: int) -> str:
    parts = [
        "leads connected" if page.leadgen_subscribed else "leads NOT connected",
        f"Instagram @{page.instagram_username}"
        if page.instagram_username
        else "no Instagram account linked",
        f"lead forms {forms}",
        f"leads in the last {PAGE_LEAD_DAYS} days {leads}",
    ]
    if page.is_current:
        parts.insert(0, "current")
    if page.location_city:
        parts.append(f"city {page.location_city}")
    return (
        f"- {named(page.name, page.external_id)} (id {page.external_id}): "
        + ", ".join(parts)
    )


def _subscription(
    db: Session, *, owner: User, now: datetime, pages_on: int
) -> list[str]:
    from app.modules.billing.selectors import capacity, days_left, live_subscription

    subscription = live_subscription(db, owner=owner)
    if subscription is None:
        return ["## Subscription", "- no live subscription"]
    return [
        "## Subscription",
        f"- plan: {subscription.plan.name}",
        f"- days left: {days_left(subscription=subscription, now=now)}",
        f"- pages allowed: {capacity(db, owner=owner).pages}, switched on: {pages_on}",
    ]


__all__ = ["account_overview", "audiences"]
