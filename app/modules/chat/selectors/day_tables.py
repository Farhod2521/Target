"""Everything one day's reports are built from: pairs, money, figures, causes and lines."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, aliased

from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import AdSet, Campaign
from app.modules.agent.causes import cause_label, cause_line
from app.modules.agent.constants import DiagnosisCause
from app.modules.agent.models import AdSetDiagnosis
from app.modules.agent.selectors.policy import diagnoses
from app.modules.chat.selectors.scope import in_subscription, subscribed_pages
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.results import screen_kind, sourced_label, words_for
from core.chat.daily import NO_FIGURE, DayCampaign
from core.metrics import Outcome


@dataclass(frozen=True, slots=True)
class DayPairs:
    """``{ad group: pair key}``, and what each pair is called and whose page."""

    of: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    pages: dict[str, str] = field(default_factory=dict)


def day_pairs(db: Session, *, owner: User, pages: Mapping[str, str]) -> DayPairs:
    """Every ad group of a chosen pair, filed under it."""
    from app.modules.ads.selectors import page_scope
    from app.modules.integrations.selectors import enabled_pages, stored_pairs

    scope = page_scope(db, owner=owner)
    chosen = {
        (pair.page.external_id, pair.account.external_id): pair
        for pair in stored_pairs(db, owner=owner, pages=enabled_pages(db, owner=owner))
    }
    of: dict[str, str] = {}
    for adset_id, page in scope.page_of.items():
        if adset_id in scope.guessed:
            continue
        account = scope.account_of.get(adset_id, "")
        pair = chosen.get((page, account))
        if pair is not None:
            of[adset_id] = page if pair.first else f"{page}:{account}"
    names = dict(pages)
    owners = {page: page for page in pages}
    for (page, external_id), pair in chosen.items():
        if pair.first:
            continue
        key = f"{page}:{external_id}"
        names[key] = f"{pages.get(page, page)} · {pair.account.name or external_id}"
        owners[key] = page
    return DayPairs(of=of, names=names, pages=owners)


@dataclass(frozen=True, slots=True)
class PageMoney:
    """One page's currency, and the campaigns that are not in it."""

    currency: str
    apart: frozenset[str] = frozenset()


def money_by_pair(db: Session, *, owner: User, fallback: str) -> dict[str, PageMoney]:
    """``{pair key: what its figures are denominated in}``."""
    from app.modules.metrics.selectors.scope import pages_campaigns

    return {
        found.key: PageMoney(currency=found.currency or fallback, apart=found.foreign)
        for found in pages_campaigns(db, owner=owner)
        if found.page is not None
    }


def apart_spend(
    db: Session, *, owner: User, money: PageMoney, day: date
) -> tuple[str, ...]:
    """What this page spent that day in a currency its report is not in."""
    from app.modules.metrics.selectors.lead_sources import other_currency_spend

    return tuple(
        format_minor(amount_minor=amount, currency=code)
        for code, amount in other_currency_spend(
            db, owner=owner, ids=money.apart, since=day, until=day
        )
    )


COLUMNS: Final[dict[str, str]] = {
    "spend": "spend_minor",
    "impressions": "impressions",
    "link_clicks": "inline_link_clicks",
    "results": "results_reported",
    "recallers": "recallers",
    "profile_visits": "profile_visits",
    "reported": "leads_reported",
}


@dataclass(frozen=True, slots=True)
class Mirror:
    """What the campaign mirror says about one campaign."""

    pk: str
    name: str
    goal: str
    delivery: str
    learning: bool
    promoted: Mapping[str, Any] | None = None
    created_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class DayTables:
    """One owner's day, before it is split by pair."""

    sums: dict[str, dict[str, int]] = field(default_factory=dict)
    usual: dict[str, dict[str, int]] = field(default_factory=dict)
    ours: dict[str, int] = field(default_factory=dict)
    ours_usual: dict[str, int] = field(default_factory=dict)
    campaign_of: dict[str, str] = field(default_factory=dict)
    elsewhere: dict[str, int] = field(default_factory=dict)
    mirror: dict[str, Mirror] = field(default_factory=dict)
    pages: dict[str, str] = field(default_factory=dict)


def day_tables(
    db: Session,
    *,
    owner: User,
    day: date,
    since: date,
    before: date,
    starts: tuple[datetime, datetime],
    ends: tuple[datetime, datetime],
) -> DayTables:
    """The day's figures and the week before it, per ad group."""
    from app.modules.ads.selectors import all_launched_campaign_ids

    groups = _groups(db, owner=owner)
    built_here = all_launched_campaign_ids(db, owner=owner)
    sums = _sums(db, owner=owner, since=day, until=day)
    return DayTables(
        sums=sums,
        usual=_sums(db, owner=owner, since=since, until=before),
        ours=_ours(db, owner=owner, since=starts[0], until=ends[0]),
        ours_usual=_ours(db, owner=owner, since=starts[1], until=ends[1]),
        campaign_of={
            group: campaign
            for group, campaign in groups.items()
            if campaign in built_here
        },
        elsewhere={
            group: sums.get(group, {}).get("spend", 0)
            for group, campaign in groups.items()
            if campaign not in built_here
        },
        mirror=_mirror(db, owner=owner),
        pages=_pages(db, owner=owner),
    )


def _groups(db: Session, *, owner: User) -> dict[str, str]:
    """``{ad group id: campaign id}`` for every group in the subscription."""
    return dict(
        db.execute(
            select(AdSet.external_id, Campaign.external_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(
                AdSet.owner_id == owner.id,
                in_subscription(Campaign.ad_account_id),
                Campaign.external_id != "",
            )
        ).all()
    )


def _sums(
    db: Session, *, owner: User, since: date, until: date
) -> dict[str, dict[str, int]]:
    """What each ad group did between two days, inclusive."""
    rows = db.execute(
        select(
            MetricsDaily.adset_external_id,
            *(
                func.sum(getattr(MetricsDaily, column)).label(name)
                for name, column in COLUMNS.items()
            ),
        )
        .where(
            MetricsDaily.owner_id == owner.id,
            in_subscription(MetricsDaily.ad_account_id),
            MetricsDaily.level == MetricLevel.ADSET,
            MetricsDaily.date >= since,
            MetricsDaily.date <= until,
            MetricsDaily.adset_external_id != "",
        )
        .group_by(MetricsDaily.adset_external_id)
    ).mappings()
    return {
        row["adset_external_id"]: {name: int(row[name] or 0) for name in COLUMNS}
        for row in rows
    }


def _ours(
    db: Session, *, owner: User, since: datetime, until: datetime
) -> dict[str, int]:
    """The enquiries this product received, per ad group."""
    from app.modules.leads.selectors import counts_by_adset

    return {
        key: counts[0]
        for key, counts in counts_by_adset(
            db, owner=owner, since=since, until=until
        ).items()
    }


def _mirror(db: Session, *, owner: User) -> dict[str, Mirror]:
    """``{campaign id: what the mirror says}`` - name, goal, state, learning."""
    from app.modules.metrics.selectors.campaigns import goal_order

    group = aliased(AdSet)
    speaker = (
        select(AdSet.id)
        .where(AdSet.owner_id == owner.id, AdSet.campaign_id == Campaign.id)
        .order_by(*goal_order())
        .limit(1)
        .scalar_subquery()
    )
    first = aliased(AdSet)
    learning = exists().where(
        group.owner_id == owner.id,
        group.campaign_id == Campaign.id,
        group.is_learning.is_(True),
    )
    rows = db.execute(
        select(
            Campaign.id,
            Campaign.external_id,
            Campaign.name,
            Campaign.delivery,
            Campaign.created_time,
            first.optimization_goal_raw,
            first.promoted_object_raw,
            learning.label("learning"),
        )
        .outerjoin(first, first.id == speaker)
        .where(Campaign.owner_id == owner.id, in_subscription(Campaign.ad_account_id))
    )
    return {
        external_id: Mirror(
            pk=str(pk),
            name=name or external_id,
            goal=goal or "",
            promoted=promoted if isinstance(promoted, Mapping) else None,
            delivery=delivery or "",
            learning=bool(is_learning),
            created_time=created_time,
        )
        for pk, external_id, name, delivery, created_time, goal, promoted, is_learning in rows
    }


def _pages(db: Session, *, owner: User) -> dict[str, str]:
    """``{page id: its name}`` for the pages the subscription carries."""
    return {
        page.external_id: page.name or page.external_id
        for page in subscribed_pages(db, owner=owner)
    }


QUIET: Final = (DiagnosisCause.NO_PROBLEM, DiagnosisCause.TOO_EARLY)


@dataclass(frozen=True, slots=True)
class DayCause:
    """One campaign's cause: the code, and the two lines a reader gets."""

    cause: str
    label: str
    line: str


def campaign_causes(
    db: Session, *, owner: User, currency: str, day: date
) -> dict[str, DayCause]:
    """``{campaign id: the cause to print}``, for the day being reported."""
    rows = list(
        db.scalars(
            diagnoses(owner).where(
                AdSetDiagnosis.until == day, AdSetDiagnosis.cause.not_in(QUIET)
            )
        )
    )
    if not rows:
        return {}
    campaigns = dict(
        db.execute(
            select(AdSet.external_id, Campaign.external_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(
                AdSet.owner_id == owner.id,
                AdSet.external_id.in_([row.adset_external_id for row in rows]),
            )
        ).all()
    )
    found: dict[str, DayCause] = {}
    for row in sorted(rows, key=_spent, reverse=True):
        key = campaigns.get(row.adset_external_id) or ""
        label = str(cause_label(row.cause))
        if not key or not label or key in found:
            continue
        found[key] = DayCause(
            cause=row.cause,
            label=label,
            line=cause_line(
                {"cause": row.cause, "signals": row.signals, "evidence": row.evidence},
                currency=currency,
            ),
        )
    return found


def _spent(row: AdSetDiagnosis) -> int:
    value = (row.evidence or {}).get("spend_minor")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


COUNTED: Final[dict[str, str]] = {
    "chat": "results",
    "call": "results",
    "view": "impressions",
    "click": "results",
    "recall": "recallers",
    "profile": "profile_visits",
    "site_lead": "reported",
}


def campaign_sums(
    *, tables: DayTables, adset_ids: Iterable[str]
) -> dict[str, dict[str, dict[str, int]]]:
    """``{campaign id: {"day"|"usual"|"ours": figures}}`` for these groups."""
    found: dict[str, dict[str, dict[str, int]]] = {}
    for adset_id in adset_ids:
        campaign = tables.campaign_of.get(adset_id, "")
        if not campaign:
            continue
        bucket = found.setdefault(
            campaign,
            {
                "day": dict.fromkeys(COLUMNS, 0),
                "usual": dict.fromkeys(COLUMNS, 0),
                "ours": {"day": 0, "usual": 0},
            },
        )
        _add(bucket["day"], tables.sums.get(adset_id, {}))
        _add(bucket["usual"], tables.usual.get(adset_id, {}))
        bucket["ours"]["day"] += tables.ours.get(adset_id, 0)
        bucket["ours"]["usual"] += tables.ours_usual.get(adset_id, 0)
    return found


def campaign_line(
    *,
    figures: Mapping[str, dict[str, int]],
    info: Mirror,
    currency: str,
    cause: DayCause | None,
) -> DayCampaign:
    """One campaign's day, rendered for the model and for the reader alike."""
    kind = screen_kind(info.goal, info.promoted)
    words = words_for(kind)
    count = _count(kind=kind, sums=figures["day"], ours=figures["ours"]["day"])
    usual = _count(kind=kind, sums=figures["usual"], ours=figures["ours"]["usual"])
    cost = _cost(figures["day"]["spend"], count, words.per)
    usual_cost = _cost(figures["usual"]["spend"], usual, words.per)
    return DayCampaign(
        name=info.name,
        kind=kind,
        state=info.delivery,
        state_label=str(_delivery_label(info.delivery)) if info.delivery else "",
        learning=info.learning,
        spend=_money(figures["day"]["spend"], currency),
        results=count,
        result_label=sourced_label(kind),
        cost=_money(cost, currency),
        cost_label=str(words.cost_label),
        usual_cost=_money(usual_cost, currency),
        reported=figures["day"]["reported"] if kind == "lead" else 0,
        spend_minor=figures["day"]["spend"],
        cost_minor=cost,
        usual_cost_minor=usual_cost,
        cause=cause.cause if cause else "",
        cause_label=cause.label if cause else "",
        cause_line=cause.line if cause else "",
    )


def _delivery_label(delivery: str) -> object:
    return Delivery(delivery).label if delivery in Delivery.values else ""


def _add(into: dict[str, int], figures: Mapping[str, int]) -> None:
    for name in COLUMNS:
        into[name] += int(figures.get(name, 0) or 0)


def _count(*, kind: Outcome, sums: Mapping[str, int], ours: int) -> int:
    if kind == "lead":
        return ours
    column = COUNTED.get(kind)
    return int(sums.get(column, 0)) if column else 0


def _cost(spend: int, count: int, per: int) -> int | None:
    return spend * per // count if count else None


def _money(amount: int | None, currency: str) -> str:
    if amount is None:
        return NO_FIGURE
    return format_minor(amount_minor=amount, currency=currency)


__all__ = [
    "COLUMNS",
    "COUNTED",
    "DayCause",
    "DayPairs",
    "DayTables",
    "Mirror",
    "PageMoney",
    "apart_spend",
    "campaign_causes",
    "campaign_line",
    "campaign_sums",
    "day_pairs",
    "day_tables",
    "money_by_pair",
]
