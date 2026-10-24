"""Which ads the leads came from, with what each lead cost; and campaigns in
a currency the page's figures cannot be added to."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from adskit import MinorUnits
from metaads import PROVIDER as META
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import EVERY_ACCOUNT, MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.facts import cabinet_where
from core.metrics import PanelTotals, share

SOURCE_PERIODS: Final[tuple[int, ...]] = (7, 30, 90)
DEFAULT_PERIOD: Final = 30
ALL_TIME: Final = 0


def other_currency_campaigns(
    db: Session,
    *,
    owner: User,
    ids: Collection[str],
    currency: str,
    accounts: Collection[AdAccount] | None = None,
) -> frozenset[str]:
    from app.modules.ads.models import Campaign

    spoken = (
        {account.currency for account in accounts}
        if accounts is not None
        else set(
            db.scalars(
                select(AdAccount.currency).where(
                    AdAccount.owner_id == owner.id,
                    AdAccount.provider == META,
                    AdAccount.is_active.is_(True),
                )
            )
        )
    )
    if not ids or len(spoken) < 2:
        return frozenset()
    return frozenset(
        str(external_id)
        for external_id in db.scalars(
            select(Campaign.external_id)
            .join(AdAccount, AdAccount.id == Campaign.ad_account_id)
            .where(
                Campaign.owner_id == owner.id,
                Campaign.external_id.in_(list(ids)),
                AdAccount.currency != currency,
            )
        )
    )


def other_currency_spend(
    db: Session, *, owner: User, ids: frozenset[str], since: date, until: date
) -> tuple[tuple[str, int], ...]:
    if not ids:
        return ()
    total = func.sum(MetricsDaily.spend_minor)
    rows = db.execute(
        select(MetricsDaily.currency, total)
        .where(
            *cabinet_where(db, owner=owner, account=EVERY_ACCOUNT),
            MetricsDaily.date >= since,
            MetricsDaily.date <= until,
            MetricsDaily.campaign_external_id.in_(list(ids)),
            MetricsDaily.currency != "",
        )
        .group_by(MetricsDaily.currency)
        .having(total > 0)
    )
    return tuple(sorted(((str(c), int(s)) for c, s in rows), key=lambda pair: -pair[1]))


@dataclass(frozen=True, slots=True)
class SourceRow:
    external_id: str
    title: str
    campaign_name: str
    campaign_id: str
    delivery: str
    delivery_label: str
    is_attributed: bool
    is_known: bool
    leads: int
    qualified: int
    unmarked: int
    newest_at: datetime | None
    spend: str
    cpl: str
    cpql: str
    share: int


@dataclass(frozen=True, slots=True)
class LeadSources:
    rows: tuple[SourceRow, ...] = ()
    days: int = DEFAULT_PERIOD
    leads: int = 0
    qualified: int = 0
    spend: str = ""
    cpl: str = ""
    cpql: str = ""
    has_cost: bool = False

    def __bool__(self) -> bool:
        return bool(self.rows)


def lead_sources(
    db: Session, *, owner: User, days: int = DEFAULT_PERIOD
) -> LeadSources:
    from app.modules.ads.selectors import ad_labels, page_advertising
    from app.modules.leads.selectors import AdTally, lead_scope, tallies_by_ad

    advertising = page_advertising(db, owner=owner)
    account = advertising.home
    tzinfo = account.tzinfo() if account is not None else ZoneInfo("UTC")
    currency = account.currency if account is not None else ""
    today = utcnow().astimezone(tzinfo).date()
    since, until = (None, None)
    if days != ALL_TIME:
        start = today - timedelta(days=days - 1)
        since, until = (
            datetime.combine(start, time.min).replace(tzinfo=tzinfo),
            utcnow(),
        )
    tallies = tallies_by_ad(
        db,
        owner=owner,
        since=since,
        until=until,
        scope=lead_scope(page=advertising.page, sole=advertising.sole),
    )
    spend = _spend_by_ad(
        db,
        owner=owner,
        days=days,
        today=today,
        campaign_ids=advertising.campaign_ids
        - other_currency_campaigns(
            db,
            owner=owner,
            ids=advertising.campaign_ids,
            currency=currency,
            accounts=advertising.accounts,
        ),
    )
    labels = ad_labels(
        db,
        owner=owner,
        external_ids=[tally.external_id for tally in tallies] + list(spend),
    )
    counted = sum(tally.leads for tally in tallies)
    seen = {tally.external_id for tally in tallies}
    barren = tuple(
        AdTally(external_id=external_id)
        for external_id, amount in spend.items()
        if external_id not in seen and amount > 0
    )
    ordered = sorted(
        tallies + barren,
        key=lambda tally: (
            0 if tally.is_attributed else 1,
            -tally.leads,
            -spend.get(tally.external_id, 0),
            tally.external_id,
        ),
    )
    rows = []
    for tally in ordered:
        label = labels.get(tally.external_id)
        spent = spend.get(tally.external_id)
        totals = PanelTotals(
            spend_minor=MinorUnits(spent or 0),
            leads=tally.leads,
            qualified=tally.qualified,
        )
        rows.append(
            SourceRow(
                external_id=tally.external_id,
                title=label.title if label is not None else tally.external_id,
                campaign_name=label.campaign_name if label is not None else "",
                campaign_id=label.campaign_id if label is not None else "",
                delivery=label.delivery if label is not None else "",
                delivery_label=(
                    Delivery(label.delivery).label
                    if label is not None and label.delivery in Delivery.values
                    else ""
                ),
                is_attributed=tally.is_attributed,
                is_known=label is not None,
                leads=tally.leads,
                qualified=tally.qualified,
                unmarked=tally.unmarked,
                newest_at=tally.newest_at,
                spend=format_minor(amount_minor=spent, currency=currency),
                cpl=format_minor(amount_minor=totals.cpl_minor, currency=currency),
                cpql=format_minor(amount_minor=totals.cpql_minor, currency=currency),
                share=share(part=tally.leads, whole=counted),
            )
        )
    qualified = sum(tally.qualified for tally in tallies)
    totals = PanelTotals(
        spend_minor=MinorUnits(sum(spend.values())), leads=counted, qualified=qualified
    )
    return LeadSources(
        rows=tuple(rows),
        days=days,
        leads=counted,
        qualified=qualified,
        has_cost=bool(spend),
        spend=format_minor(amount_minor=sum(spend.values()) or None, currency=currency),
        cpl=format_minor(amount_minor=totals.cpl_minor, currency=currency),
        cpql=format_minor(amount_minor=totals.cpql_minor, currency=currency),
    )


def _spend_by_ad(
    db: Session, *, owner: User, days: int, today: date, campaign_ids: frozenset[str]
) -> dict[str, int]:
    if days == ALL_TIME:
        return {}
    rows = db.execute(
        select(MetricsDaily.external_id, func.sum(MetricsDaily.spend_minor))
        .where(
            *cabinet_where(
                db, owner=owner, level=MetricLevel.AD, account=EVERY_ACCOUNT
            ),
            MetricsDaily.date >= today - timedelta(days=days - 1),
            MetricsDaily.date <= today,
            MetricsDaily.campaign_external_id.in_(list(campaign_ids)),
            MetricsDaily.external_id != "",
        )
        .group_by(MetricsDaily.external_id)
    )
    return {external_id: int(spend) for external_id, spend in rows if spend}
