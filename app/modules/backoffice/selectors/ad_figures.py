"""The office's advertising figures: what targetolog.ai's own ads cost and
what came of them, for one window of days.

Spend is read only from the office's ad account (``OFFICE_AD_ACCOUNT``) and
only for the campaigns the superuser picked; Meta's daily figures are read,
so a campaign deleted since still counts for the days it ran. Everything
else is the whole platform's, not a picked campaign's: a signed-up account
does not say which ad brought it (that is written only since 2026-11-19),
so ROAS and the price of a customer are blended - all takings, all new
payers, against the picked spend.

- spend: the picked campaigns' spend, in the account's currency and in so'm
  at each day's Central Bank rate;
- revenue: paid bills in so'm, as the takings card counts them;
- ROAS: revenue / spend in so'm;
- CAC: spend in so'm / customers whose first paid plan fell in the window;
- conversion: customers who joined in the window and paid a plan, of all
  who joined in it;
- deal time: the median from joining to the first paid plan that is not
  Start, for those whose first such bill fell in the window - Start is
  bought minutes after signing up and would read as no time at all.

A day the bank has no rate for leaves the so'm spend, ROAS and CAC unknown
(``None``) and says how many days; it is never guessed.
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign
from app.modules.backoffice.models import OfficeAdCampaign
from app.modules.billing.constants import DEFAULT_PLAN_CODE, InvoiceKind, InvoiceStatus
from app.modules.billing.models import Invoice, Plan
from app.modules.integrations.models import AdAccount
from app.modules.integrations.selectors.demo import not_demo
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.services.rates import rates_for
from core.metrics.exchange import HOME

# A campaign Meta no longer lists: only its daily figures are left.
GONE = "DELETED"
LINK = re.compile(r'"link":\s*"(https?://[^"]+)"')


def office_account(db: Session) -> AdAccount | None:
    """The office's ad account, when it is connected to anyone's cabinet."""
    wanted = settings.office_ad_account.strip()
    if not wanted:
        return None
    return db.scalar(
        select(AdAccount)
        .where(AdAccount.external_id == wanted)
        .order_by(AdAccount.created_at)
        .limit(1)
    )


def picked_ids(db: Session) -> set[str]:
    return set(db.scalars(select(OfficeAdCampaign.campaign_external_id)))


# -- the list to pick from -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CampaignRow:
    external_id: str
    name: str
    status: str
    sites: tuple[str, ...]
    first_day: date | None
    last_day: date | None
    spend_minor: int
    leads: int
    picked: bool


def _host(url: str) -> str:
    try:
        host = urlsplit(url.strip()).hostname or ""
    except ValueError:
        return ""
    return host.removeprefix("www.").lower()


def _sites(db: Session, account: AdAccount) -> dict[str, set[str]]:
    """The sites each campaign's ads link to, by the campaign."""
    rows = db.execute(
        select(Campaign.external_id, AdCreative.link_url, AdCreative.story_raw)
        .join(AdSet, AdSet.campaign_id == Campaign.id)
        .join(Ad, Ad.adset_id == AdSet.id)
        .join(AdCreative, AdCreative.external_id == Ad.creative_external_id)
        .where(Campaign.ad_account_id == account.id)
    )
    found: dict[str, set[str]] = {}
    for campaign, link, story in rows:
        links = [link or ""]
        if story:
            links += LINK.findall(json.dumps(story, ensure_ascii=False))
        hosts = {_host(url) for url in links} - {""}
        found.setdefault(campaign, set()).update(hosts)
    return found


def campaign_rows(db: Session, account: AdAccount) -> list[CampaignRow]:
    """Every campaign the account ever had: those Meta still lists and those
    only its daily figures remember. The newest first."""
    figures = {
        external_id: (name, first, last, int(spend), int(leads))
        for external_id, name, first, last, spend, leads in db.execute(
            select(
                MetricsDaily.campaign_external_id,
                func.max(MetricsDaily.object_name),
                func.min(MetricsDaily.date),
                func.max(MetricsDaily.date),
                func.coalesce(func.sum(MetricsDaily.spend_minor), 0),
                func.coalesce(func.sum(MetricsDaily.leads_reported), 0),
            )
            .where(
                MetricsDaily.ad_account_id == account.id,
                MetricsDaily.level == MetricLevel.CAMPAIGN,
                MetricsDaily.campaign_external_id != "",
            )
            .group_by(MetricsDaily.campaign_external_id)
        )
    }
    listed = {
        row.external_id: row
        for row in db.scalars(
            select(Campaign).where(Campaign.ad_account_id == account.id)
        )
    }
    sites = _sites(db, account)
    picked = picked_ids(db)
    out: list[CampaignRow] = []
    for external_id in set(figures) | set(listed):
        name, first, last, spend, leads = figures.get(
            external_id, ("", None, None, 0, 0)
        )
        campaign = listed.get(external_id)
        out.append(
            CampaignRow(
                external_id=external_id,
                name=(campaign.name if campaign else "") or name or external_id,
                status=campaign.effective_status if campaign else GONE,
                sites=tuple(sorted(sites.get(external_id, ()))),
                first_day=first,
                last_day=last,
                spend_minor=spend,
                leads=leads,
                picked=external_id in picked,
            )
        )

    def started(row: CampaignRow) -> date:
        campaign = listed.get(row.external_id)
        made = campaign.created_time if campaign else None
        return made.date() if made else date.min

    out.sort(key=lambda row: (row.last_day or date.min, started(row)), reverse=True)
    return out


def known_ids(db: Session, account: AdAccount) -> set[str]:
    """Campaign ids that belong to the account, to refuse any other."""
    return {row.external_id for row in campaign_rows(db, account)}


# -- the figures -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdFigures:
    account_name: str
    account_found: bool
    picked: int
    spend: tuple[tuple[str, int], ...]
    spend_home_minor: int | None
    unpriced_days: int
    revenue_minor: int
    roas: float | None
    new_payers: int
    cac_minor: int | None
    joined: int
    joined_paid: int
    conversion_pct: float | None
    deals: int
    deal_seconds: int | None


def _customers() -> Any:
    return and_(
        User.is_staff.is_(False), User.crm_owner_id.is_(None), not_demo(User.id)
    )


def _paid_plan() -> Any:
    return and_(
        Invoice.archived_at.is_(None),
        Invoice.status == InvoiceStatus.PAID,
        Invoice.kind == InvoiceKind.PLAN,
        Invoice.amount_minor > 0,
        Invoice.paid_at.is_not(None),
    )


def _spend(
    db: Session, *, account: AdAccount | None, picked: set[str], start: date, end: date
) -> tuple[tuple[tuple[str, int], ...], int | None, int]:
    if account is None or not picked:
        return (), (0 if account is not None else None), 0
    rows = db.execute(
        select(
            MetricsDaily.date,
            MetricsDaily.currency,
            func.sum(MetricsDaily.spend_minor),
        )
        .where(
            MetricsDaily.ad_account_id == account.id,
            MetricsDaily.level == MetricLevel.CAMPAIGN,
            MetricsDaily.campaign_external_id.in_(picked),
            MetricsDaily.date >= start,
            MetricsDaily.date <= end,
        )
        .group_by(MetricsDaily.date, MetricsDaily.currency)
    ).all()
    per_currency: dict[str, int] = {}
    rates = rates_for(db, currencies={currency for _, currency, _ in rows})
    home = 0
    unpriced: set[date] = set()
    for day, currency, amount in rows:
        amount = int(amount or 0)
        per_currency[currency] = per_currency.get(currency, 0) + amount
        if not amount:
            continue
        priced = rates.convert(
            amount_minor=amount, source=currency, target=HOME, day=day
        )
        if priced is None:
            unpriced.add(day)
        else:
            home += priced
    spend = tuple(sorted(per_currency.items()))
    return spend, (None if unpriced else home), len(unpriced)


def _revenue(db: Session, *, since: Any, until: Any) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Invoice.amount_minor), 0)).where(
                Invoice.archived_at.is_(None),
                Invoice.status == InvoiceStatus.PAID,
                Invoice.paid_at >= since,
                Invoice.paid_at < until,
                or_(Invoice.amount_minor != 0, Invoice.wallet_minor != 0),
                Invoice.currency == HOME,
                not_demo(Invoice.owner_id),
            )
        )
        or 0
    )


def _new_payers(db: Session, *, since: Any, until: Any) -> int:
    first = (
        select(Invoice.owner_id, func.min(Invoice.paid_at).label("first"))
        .where(_paid_plan())
        .group_by(Invoice.owner_id)
        .subquery()
    )
    return int(
        db.scalar(
            select(func.count())
            .select_from(first)
            .join(User, User.id == first.c.owner_id)
            .where(_customers(), first.c.first >= since, first.c.first < until)
        )
        or 0
    )


def _conversion(db: Session, *, since: Any, until: Any) -> tuple[int, int]:
    joined = and_(_customers(), User.date_joined >= since, User.date_joined < until)
    paid = select(Invoice.owner_id).where(_paid_plan())
    total = int(db.scalar(select(func.count(User.id)).where(joined)) or 0)
    bought = int(
        db.scalar(select(func.count(User.id)).where(joined, User.id.in_(paid))) or 0
    )
    return total, bought


def _deals(db: Session, *, since: Any, until: Any) -> list[float]:
    first = (
        select(Invoice.owner_id, func.min(Invoice.paid_at).label("first"))
        .join(Plan, Plan.id == Invoice.plan_id)
        .where(_paid_plan(), Plan.code != DEFAULT_PLAN_CODE)
        .group_by(Invoice.owner_id)
        .subquery()
    )
    rows = db.execute(
        select(first.c.first, User.date_joined)
        .join(User, User.id == first.c.owner_id)
        .where(_customers(), first.c.first >= since, first.c.first < until)
    )
    return [max((paid - joined).total_seconds(), 0.0) for paid, joined in rows]


def ad_figures(db: Session, *, window: Any) -> AdFigures:
    """The six figures for the window (``selectors.dashboard.Window``)."""
    account = office_account(db)
    picked = picked_ids(db)
    since, until = window.since, window.until
    spend, home, unpriced = _spend(
        db, account=account, picked=picked, start=window.start, end=window.end
    )
    revenue = _revenue(db, since=since, until=until)
    payers = _new_payers(db, since=since, until=until)
    joined, joined_paid = _conversion(db, since=since, until=until)
    deals = _deals(db, since=since, until=until)
    return AdFigures(
        account_name=account.name if account else settings.office_ad_account,
        account_found=account is not None,
        picked=len(picked),
        spend=spend,
        spend_home_minor=home,
        unpriced_days=unpriced,
        revenue_minor=revenue,
        roas=round(revenue / home, 2) if home else None,
        new_payers=payers,
        cac_minor=round(home / payers) if home is not None and payers else None,
        joined=joined,
        joined_paid=joined_paid,
        conversion_pct=round(joined_paid * 100 / joined, 1) if joined else None,
        deals=len(deals),
        deal_seconds=round(median(deals)) if deals else None,
    )


__all__ = [
    "AdFigures",
    "CampaignRow",
    "ad_figures",
    "campaign_rows",
    "known_ids",
    "office_account",
    "picked_ids",
]
