"""Campaigns across the subscription, and one campaign all the way down."""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.chat.selectors.briefs import delivery_label, group_digest
from app.modules.chat.selectors.lookups.common import (
    in_subscription,
    money,
    named,
    origin,
    refused,
    section,
    window,
)
from app.modules.chat.selectors.lookups.sums import (
    figures_by,
    group_budgets,
    kinds_by_campaign,
    leads_by,
    spenders_by,
)
from app.modules.chat.selectors.readings import diagnoses_for
from app.modules.integrations.models import AdAccount
from app.modules.metrics.selectors.results import screen_kind, words_for
from core.chat.lookups import (
    AD_ROWS,
    ADSET_ROWS,
    CAMPAIGN_ROWS,
    CampaignList,
    CampaignLookup,
)
from core.chat.rungs import adset_line
from core.metrics.outcomes import Outcome

CAMPAIGNS_READ: Final = 300

COUNTED: Final[dict[str, str]] = {
    "link_clicks": "link_clicks",
    "results": "results",
    "impressions": "shown",
    "recallers": "recallers",
    "profile_visits": "profile_visits",
    "leads_reported": "reported",
}


def list_campaigns(
    db: Session,
    *,
    owner: User,
    arguments: CampaignList,
    scope: PageScope,
    now: datetime,
) -> str:
    """The subscription's campaigns, biggest spender over the window first."""
    since, until = window(db, owner=owner, days=arguments.days)
    query = select(Campaign).where(
        Campaign.owner_id == owner.id,
        in_subscription(Campaign.ad_account_id),
    )
    if scope.blocked:
        query = query.where(Campaign.external_id.not_in(list(scope.blocked)))
    if arguments.account_id:
        query = query.join(AdAccount, AdAccount.id == Campaign.ad_account_id).where(
            AdAccount.external_id == arguments.account_id
        )
    if arguments.status == "running":
        query = query.where(Campaign.delivery == Delivery.ACTIVE)
    elif arguments.status == "stopped":
        query = query.where(Campaign.delivery != Delivery.ACTIVE)
    campaigns = read_campaigns(db, query, owner=owner, since=since, until=until)
    lines = campaign_lines(
        db, owner=owner, campaigns=campaigns, since=since, until=until, scope=scope
    )
    out = section(
        f"Campaigns, {since} to {until}",
        lines[:CAMPAIGN_ROWS],
        empty="no campaigns match",
    )
    if len(lines) > CAMPAIGN_ROWS:
        out.append(f"- and {len(lines) - CAMPAIGN_ROWS} more that spent less")
    return "\n".join(out)


def campaign_details(
    db: Session,
    *,
    owner: User,
    arguments: CampaignLookup,
    scope: PageScope,
    now: datetime,
) -> str:
    """One campaign, its ad groups and its adverts, over the window."""
    campaign = db.scalar(
        select(Campaign)
        .where(
            Campaign.owner_id == owner.id,
            in_subscription(Campaign.ad_account_id),
            Campaign.external_id == arguments.campaign_id,
        )
        .limit(1)
    )
    if campaign is None:
        return (
            f"No campaign with id {arguments.campaign_id} in the subscription. "
            "Use find to look it up by name."
        )
    if not scope.allows_campaign(campaign.external_id):
        return refused(
            scope=scope,
            kind="campaign",
            level="campaign",
            external_id=campaign.external_id,
        )
    since, until = window(db, owner=owner, days=arguments.days)
    lines = [
        f"## Campaign, {since} to {until}",
        *campaign_lines(
            db, owner=owner, campaigns=[campaign], since=since, until=until, scope=scope
        ),
    ]
    if campaign.issue_summary:
        lines.append(f"- provider says: {campaign.issue_summary}")
    lines += [
        "",
        *_groups(
            db, owner=owner, campaign=campaign, since=since, until=until, scope=scope
        ),
    ]
    lines += [
        "",
        *_adverts(
            db, owner=owner, campaign=campaign, since=since, until=until, scope=scope
        ),
    ]
    return "\n".join(lines)


def _groups(
    db: Session,
    *,
    owner: User,
    campaign: Campaign,
    since: date,
    until: date,
    scope: PageScope,
) -> list[str]:
    groups = (
        list(
            db.scalars(
                select(AdSet)
                .where(
                    AdSet.owner_id == owner.id,
                    AdSet.campaign_id == campaign.id,
                    AdSet.external_id.in_(list(scope.adset_ids)),
                )
                .order_by(AdSet.external_id)
                .limit(ADSET_ROWS)
            )
        )
        if scope.adset_ids
        else []
    )
    ids = [row.external_id for row in groups]
    column = "adset_external_id"
    sums = figures_by(db, owner=owner, column=column, ids=ids, since=since, until=until)
    leads = leads_by(db, owner=owner, column=column, ids=ids, since=since, until=until)
    diagnosed = diagnoses_for(db, owner=owner, adset_ids=ids)
    rows = []
    for row in groups:
        line = adset_line(
            group_digest(
                page=scope.name_of(scope.page_of.get(row.external_id, "")),
                row=row,
                figures=sums.get(row.external_id, {}),
                leads=leads.get(row.external_id, 0),
                diagnosis=diagnosed.get(row.external_id),
            )
        )
        budget = (
            f", daily budget {money(row.daily_budget_minor, campaign.currency)}"
            if row.daily_budget_minor
            else ""
        )
        rows.append(f"{line} [id {row.external_id}{budget}]")
    return section("Ad groups", rows, empty="no ad groups mirrored yet")


def _adverts(
    db: Session,
    *,
    owner: User,
    campaign: Campaign,
    since: date,
    until: date,
    scope: PageScope,
) -> list[str]:
    adverts = (
        list(
            db.scalars(
                select(Ad)
                .join(AdSet, AdSet.id == Ad.adset_id)
                .where(
                    Ad.owner_id == owner.id,
                    AdSet.campaign_id == campaign.id,
                    AdSet.external_id.in_(list(scope.adset_ids)),
                )
                .order_by(AdSet.external_id, Ad.external_id)
                .limit(AD_ROWS)
            )
        )
        if scope.adset_ids
        else []
    )
    ids = [row.external_id for row in adverts]
    column = "ad_external_id"
    sums = figures_by(db, owner=owner, column=column, ids=ids, since=since, until=until)
    leads = leads_by(db, owner=owner, column=column, ids=ids, since=since, until=until)
    rows = []
    for row in adverts:
        figures = sums.get(row.external_id, {})
        spend = int(figures.get("spend") or 0)
        kind = screen_kind(
            row.adset.optimization_goal_raw, row.adset.promoted_object_raw
        )
        counted, count = counted_result(
            kind=kind, figures=figures, leads=leads.get(row.external_id, 0)
        )
        parts = [
            str(delivery_label(row.delivery)),
            f"spend {money(spend, campaign.currency)}",
        ]
        if counted:
            parts.append(counted)
        if count and kind != "view":
            parts.append(f"cost each {money(spend // count, campaign.currency)}")
        parts += [
            f"shown {int(figures.get('shown') or 0)}",
            f"link clicks {int(figures.get('link_clicks') or 0)}",
        ]
        line = (
            f"- {named(row.name, row.external_id)} (id {row.external_id}) in ad group "
            f"{named(row.adset.name, row.adset.external_id)} - " + ", ".join(parts)
        )
        if row.issue_summary:
            line += f", provider says: {row.issue_summary}"
        rows.append(line)
    return section("Adverts", rows, empty="no adverts mirrored yet")


def read_campaigns(
    db: Session,
    query: Select[tuple[Campaign]],
    *,
    owner: User,
    since: date,
    until: date,
) -> list[Campaign]:
    """The spenders of this window first, then the newest of the rest."""
    spent = spenders_by(
        db, owner=owner, column="campaign_external_id", since=since, until=until
    )
    found = (
        list(
            db.scalars(
                query.where(Campaign.external_id.in_(list(spent)))
                .order_by(Campaign.created_time.desc())
                .limit(CAMPAIGNS_READ)
            )
        )
        if spent
        else []
    )
    room = CAMPAIGNS_READ - len(found)
    if room <= 0:
        return found
    rest = query.order_by(Campaign.created_time.desc()).limit(room)
    if found:
        rest = rest.where(
            Campaign.external_id.not_in([row.external_id for row in found])
        )
    return found + list(db.scalars(rest))


def campaign_lines(
    db: Session,
    *,
    owner: User,
    campaigns: list[Campaign],
    since: date,
    until: date,
    scope: PageScope,
) -> list[str]:
    """One line per campaign, biggest spender first. Four queries for all."""
    ids = [row.external_id for row in campaigns]
    column = "campaign_external_id"
    sums = figures_by(db, owner=owner, column=column, ids=ids, since=since, until=until)
    leads = leads_by(db, owner=owner, column=column, ids=ids, since=since, until=until)
    kinds = kinds_by_campaign(db, owner=owner, ids=ids)
    budgets = group_budgets(db, owner=owner, ids=ids)
    ordered = sorted(
        campaigns,
        key=lambda row: sums.get(row.external_id, {}).get("spend") or 0,
        reverse=True,
    )
    on_page = scope.page_of_campaign()
    return [
        _one_line(
            row,
            figures=sums.get(row.external_id, {}),
            leads=leads.get(row.external_id, 0),
            kind=kinds.get(row.external_id, "lead"),
            budget=row.daily_budget_minor or budgets.get(row.external_id, 0),
            page=scope.name_of(on_page.get(row.external_id, "")),
        )
        + origin(scope, level="campaign", external_id=row.external_id)
        for row in ordered
    ]


def _one_line(
    row: Campaign,
    *,
    figures: Mapping[str, Any],
    leads: int,
    kind: Outcome,
    budget: int,
    page: str = "",
) -> str:
    currency = row.currency or (row.ad_account.currency if row.ad_account else "")
    spend = int(figures.get("spend") or 0)
    parts = [str(delivery_label(row.delivery))]
    if page:
        parts.append(f"page {named(page, '')}")
    if words_for(kind).field:
        parts.append(f"optimised for: {words_for(kind).label}")
    if budget:
        parts.append(f"daily budget {money(budget, currency)}")
    parts.append(f"spend {money(spend, currency)}")
    counted, count = counted_result(kind=kind, figures=figures, leads=leads)
    if counted:
        parts.append(counted)
    if count and kind != "view":
        parts.append(f"cost each {money(spend // count, currency)}")
    parts.append(f"shown {int(figures.get('shown') or 0)} times")
    if row.created_time is not None:
        parts.append(f"created {row.created_time:%Y-%m-%d}")
    where = (
        f", ad account {named(row.ad_account.name, row.ad_account.external_id)}"
        if row.ad_account
        else ""
    )
    return (
        f"- {named(row.name, row.external_id)} (id {row.external_id}{where}) - "
        + ", ".join(parts)
    )


def counted_result(
    *, kind: Outcome, figures: Mapping[str, Any], leads: int
) -> tuple[str, int]:
    """The result line for this kind, and the count a cost divides by."""
    if kind == "lead":
        reported = int(figures.get("reported") or 0)
        text = f"leads received {leads}"
        if reported != leads:
            text += f" (the provider counted {reported})"
        return text, max(leads, reported)
    words = words_for(kind)
    column = COUNTED.get(words.field, "")
    if not column:
        return "", 0
    count = int(figures.get(column) or 0)
    return f"{words.label}: {count}", count


__all__ = [
    "CAMPAIGNS_READ",
    "campaign_details",
    "campaign_lines",
    "counted_result",
    "list_campaigns",
    "read_campaigns",
]
