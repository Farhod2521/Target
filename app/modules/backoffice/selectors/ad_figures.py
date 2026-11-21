"""The office's advertising figures: what targetolog.ai's own ads cost and
what the people they brought have paid, for one window of days.

The superuser picks the campaigns (only the office's ad account,
``OFFICE_AD_ACCOUNT``) and the plans that count. The people counted are
those who signed up in the window and were brought by a picked campaign;
what they paid for a picked plan up to now is their revenue. A seat or a
page bought is no plan and never counted.

- spend: the picked campaigns' spend over the window, in the account's
  currency and in so'm at each day's Central Bank rate;
- sign-ups: from ``EXACT_FROM`` each sign-up's utm marks name its ad set or
  campaign; before it, the picked campaigns' Meta results (capped by the
  sign-ups of those days) stand in for them - see ``ad_figures``;
- revenue: their paid bills for the picked plans, up to now;
- ROAS: revenue / spend in so'm;
- CAC: spend in so'm / those who paid;
- conversion: those who paid / those who signed up;
- deal time: the median from signing up to the first paid picked plan.

A day the bank has no rate for leaves the so'm spend, ROAS and CAC unknown
(``None``) and says how many days; it is never guessed.
"""

import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Final
from urllib.parse import unquote_plus, urlsplit

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign
from app.modules.backoffice.models import OfficeAcquisitionPlan, OfficeAdCampaign
from app.modules.billing.constants import InvoiceKind, InvoiceStatus
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

# The first whole day sign-ups carry the landing link's utm_* marks (from
# 2026-11-19 10:27 Tashkent). From it on a sign-up is tied to its campaign;
# before it only the count can be estimated.
EXACT_FROM: Final = date(2026, 11, 20)


@dataclass(frozen=True, slots=True)
class PlanRow:
    id: str
    name: str
    code: str
    is_active: bool
    paid: int
    picked: bool


def picked_plan_ids(db: Session) -> set[uuid.UUID]:
    return set(db.scalars(select(OfficeAcquisitionPlan.plan_id)))


def plan_rows(db: Session) -> list[PlanRow]:
    """Every plan, the ones on sale first, with how many bills paid it."""
    paid = dict(
        db.execute(
            select(Invoice.plan_id, func.count(Invoice.id))
            .where(_paid_plan())
            .group_by(Invoice.plan_id)
        ).all()
    )
    picked = picked_plan_ids(db)
    plans = db.scalars(
        select(Plan).order_by(Plan.is_active.desc(), Plan.sort_order, Plan.name)
    )
    return [
        PlanRow(
            id=str(plan.id),
            name=plan.name,
            code=plan.code,
            is_active=plan.is_active,
            paid=int(paid.get(plan.id, 0)),
            picked=plan.id in picked,
        )
        for plan in plans
    ]


@dataclass(frozen=True, slots=True)
class AdFigures:
    account_name: str
    account_found: bool
    picked: int
    plans_picked: int
    spend: tuple[tuple[str, int], ...]
    spend_home_minor: int | None
    unpriced_days: int
    signups: float
    payers: float
    revenue_minor: int
    roas: float | None
    cac_minor: int | None
    conversion_pct: float | None
    deals: int
    deal_seconds: int | None
    # The window's first and last day counted by estimate; None when the
    # whole window is counted sign-up by sign-up.
    estimated_from: date | None
    estimated_until: date | None


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


def _leads(
    db: Session, *, account: AdAccount | None, picked: set[str], start: date, end: date
) -> int:
    """The results Meta counted for the picked campaigns: on targetolog.ai a
    result is one account that signed up and reached the prices."""
    if account is None or not picked:
        return 0
    return int(
        db.scalar(
            select(func.coalesce(func.sum(MetricsDaily.leads_reported), 0)).where(
                MetricsDaily.ad_account_id == account.id,
                MetricsDaily.level == MetricLevel.CAMPAIGN,
                MetricsDaily.campaign_external_id.in_(picked),
                MetricsDaily.date >= start,
                MetricsDaily.date <= end,
            )
        )
        or 0
    )


def _norm(name: str) -> str:
    return " ".join(unquote_plus(name).split()).casefold()


@dataclass(frozen=True, slots=True)
class _Marks:
    """What a sign-up's marks are read against."""

    adsets: dict[str, str]  # every ad set of the account -> its campaign
    picked: set[str]
    picked_names: set[str]

    def brought(self, utm: dict[str, Any]) -> bool:
        """Whether a picked campaign brought this sign-up. The ad set's id
        decides when it is one of the account's; else the campaign's id, else
        its name (Meta writes a space as ``+`` in some links)."""
        term = str(utm.get("term") or "").strip()
        if term in self.adsets:
            return self.adsets[term] in self.picked
        campaign = str(utm.get("campaign") or "").strip()
        if not campaign:
            return False
        return campaign in self.picked or _norm(campaign) in self.picked_names


def _marks(db: Session, *, account: AdAccount, picked: set[str]) -> _Marks:
    adsets: dict[str, str] = {}
    for adset, campaign in db.execute(
        select(MetricsDaily.adset_external_id, MetricsDaily.campaign_external_id)
        .where(
            MetricsDaily.ad_account_id == account.id,
            MetricsDaily.adset_external_id != "",
        )
        .distinct()
    ):
        adsets[adset] = campaign
    for adset, campaign in db.execute(
        select(AdSet.external_id, Campaign.external_id)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .where(Campaign.ad_account_id == account.id)
    ):
        adsets[adset] = campaign
    names = {
        row.name for row in campaign_rows(db, account) if row.external_id in picked
    }
    return _Marks(
        adsets=adsets,
        picked=picked,
        picked_names={_norm(name) for name in names if name},
    )


@dataclass(frozen=True, slots=True)
class _Cohort:
    people: int
    payers: int
    revenue: int
    deals: list[float]


def _cohort(db: Session, owners: list[uuid.UUID], plans: set[uuid.UUID]) -> _Cohort:
    """What these accounts paid for the picked plans, up to now."""
    if not owners or not plans:
        return _Cohort(people=len(owners), payers=0, revenue=0, deals=[])
    rows = db.execute(
        select(
            Invoice.owner_id,
            func.min(Invoice.paid_at),
            func.sum(Invoice.amount_minor),
            User.date_joined,
        )
        .join(User, User.id == Invoice.owner_id)
        .where(
            _paid_plan(),
            Invoice.currency == HOME,
            Invoice.plan_id.in_(plans),
            Invoice.owner_id.in_(owners),
        )
        .group_by(Invoice.owner_id, User.date_joined)
    ).all()
    return _Cohort(
        people=len(owners),
        payers=len(rows),
        revenue=sum(int(total or 0) for _, _, total, _ in rows),
        deals=[
            max((first - joined).total_seconds(), 0.0)
            for _, first, _, joined in rows
            if first is not None
        ],
    )


def _joined(*, since: datetime, until: datetime) -> Any:
    return and_(_customers(), User.date_joined >= since, User.date_joined < until)


def _weighted_median(items: list[tuple[float, float]]) -> float | None:
    """The middle value when each value counts as much as its weight."""
    items = sorted((value, weight) for value, weight in items if weight > 0)
    total = sum(weight for _, weight in items)
    if not total:
        return None
    running = 0.0
    for value, weight in items:
        running += weight
        if running >= total / 2:
            return value
    return items[-1][0]


def ad_figures(db: Session, *, window: Any) -> AdFigures:
    """The six figures for the window (``selectors.dashboard.Window``): the
    people who signed up in it from the picked campaigns, and what they have
    paid for the picked plans up to now.

    From ``EXACT_FROM`` on, each sign-up's marks say whether a picked
    campaign brought it. Before it nobody can be told apart, so the picked
    campaigns' Meta results over those days stand for their sign-ups -
    never more than signed up in those days, taken over the whole stretch
    because Meta writes a result on the day of the tap - and what those days'
    sign-ups paid is shared out in the same proportion."""
    account = office_account(db)
    picked = picked_ids(db)
    plans = picked_plan_ids(db)
    spend, home, unpriced = _spend(
        db, account=account, picked=picked, start=window.start, end=window.end
    )
    signups = payers = 0.0
    revenue = 0.0
    deals: list[tuple[float, float]] = []
    estimated_from = estimated_until = None
    zone = window.since.tzinfo

    if window.start < EXACT_FROM:
        last = min(window.end, EXACT_FROM - timedelta(days=1))
        estimated_from, estimated_until = window.start, last
        owners = list(
            db.scalars(
                select(User.id).where(
                    _joined(
                        since=window.since,
                        until=datetime.combine(
                            last + timedelta(days=1), time.min, zone
                        ),
                    )
                )
            )
        )
        found = _cohort(db, owners, plans)
        leads = _leads(db, account=account, picked=picked, start=window.start, end=last)
        counted = min(leads, found.people)
        share = counted / found.people if found.people else 0.0
        signups += counted
        payers += found.payers * share
        revenue += found.revenue * share
        deals += [(value, share) for value in found.deals]

    if window.end >= EXACT_FROM and account is not None and picked:
        first = max(window.start, EXACT_FROM)
        marks = _marks(db, account=account, picked=picked)
        owners = [
            owner
            for owner, utm in db.execute(
                select(User.id, User.signup_utm).where(
                    _joined(
                        since=datetime.combine(first, time.min, zone),
                        until=window.until,
                    ),
                    User.signup_utm != {},
                )
            )
            if marks.brought(utm or {})
        ]
        found = _cohort(db, owners, plans)
        signups += found.people
        payers += found.payers
        revenue += found.revenue
        deals += [(value, 1.0) for value in found.deals]

    middle = _weighted_median(deals)
    return AdFigures(
        account_name=account.name if account else settings.office_ad_account,
        account_found=account is not None,
        picked=len(picked),
        plans_picked=len(plans),
        spend=spend,
        spend_home_minor=home,
        unpriced_days=unpriced,
        signups=round(signups, 1),
        payers=round(payers, 1),
        revenue_minor=round(revenue),
        roas=round(revenue / home, 2) if home and plans else None,
        cac_minor=round(home / payers) if home is not None and payers else None,
        conversion_pct=round(payers * 100 / signups, 1) if signups else None,
        deals=sum(1 for _, weight in deals if weight >= 1.0)
        + round(sum(weight for _, weight in deals if weight < 1.0)),
        deal_seconds=round(middle) if middle is not None else None,
        estimated_from=estimated_from,
        estimated_until=estimated_until,
    )


__all__ = [
    "EXACT_FROM",
    "AdFigures",
    "CampaignRow",
    "PlanRow",
    "ad_figures",
    "campaign_rows",
    "known_ids",
    "office_account",
    "picked_ids",
    "picked_plan_ids",
    "plan_rows",
]
