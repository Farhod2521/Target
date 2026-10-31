"""Version 2 of the ads figures: what the first version's rows lose on the way.

Version 1 stays as it is for the screens already open in people's browsers.
These answers take its rows and put back what the chips cannot carry: link
clicks, a reach nobody counted as unknown rather than nought, the result of
an ad set bought for an event on the advertiser's site, and a kind that
agrees with the figure beside it.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from adskit import MinorUnits
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.contract import Money
from app.modules.accounts.models import User
from app.modules.ads import selectors
from app.modules.ads.contract.listing import ListAsk, campaign_list, figures_range
from app.modules.ads.contract.manager import manager
from app.modules.metrics.constants import EVERY_ACCOUNT, MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.ranges import CUSTOM, Range
from app.modules.metrics.selectors.facts import (
    People,
    cabinet_where,
    people_counts,
)
from app.modules.metrics.selectors.results import screen_kind
from core.metrics import cost_per
from core.metrics.outcomes import SITE_GOAL, campaign_goal

M = MetricsDaily
CONVERSION_KIND: Final = "conversion"
UNCOUNTED_KIND: Final = "other"
RECALL_KIND: Final = "recall"
# The kind the screens name for each outcome, where the two differ or the
# first version guessed it from the campaign's objective.
OUTCOME_KINDS: Final[dict[str, str]] = {
    "lead": "lead",
    "site_lead": "site",
    "chat": "chat",
    "call": "call",
    "view": "view",
    "click": "click",
    "profile": "profile",
    "recall": RECALL_KIND,
}
# Launched for this: no ad set goal says so, and the launch is what knows.
KEPT_KINDS: Final = frozenset({"sub"})
CONVERSION_LABELS: Final[dict[str, str]] = {
    "COMPLETE_REGISTRATION": "Ro'yxatdan o'tishlar",
    "PURCHASE": "Xaridlar",
    "ADD_TO_CART": "Savatga qo'shishlar",
    "INITIATED_CHECKOUT": "To'lovni boshlashlar",
    "CONTACT": "Aloqaga chiqishlar",
    "SCHEDULE": "Yozilishlar",
    "SUBSCRIBE": "Obunalar",
}
CONVERSION_LABEL: Final = "Konversiyalar"
# Goals the outcomes do not name, whose events Meta's results column does count.
COUNTED_GOALS: Final[dict[str, str]] = {"VISIT_INSTAGRAM_PROFILE": "profile"}


@dataclass(frozen=True, slots=True)
class Exact:
    link_clicks: int = 0
    results: int = 0
    impressions: int = 0


@dataclass(frozen=True, slots=True)
class Shown:
    """What a row's result is, and whether the event count stands for it."""

    kind: str
    label: str | None = None
    counts_events: bool = False


# Which rows answer for each level, and the column that names their object.
# A campaign is its ad sets' rows, as in the first version's figures.
_READS: Final[dict[str, tuple[MetricLevel, Any]]] = {
    MetricLevel.CAMPAIGN: (MetricLevel.ADSET, M.campaign_external_id),
    MetricLevel.ADSET: (MetricLevel.ADSET, M.adset_external_id),
    MetricLevel.AD: (MetricLevel.AD, M.external_id),
}


def _exact(
    db: Session, *, owner: User, level: str, ids: Iterable[str], date_range: Range
) -> dict[str, Exact]:
    wanted = [one for one in ids if one]
    if not wanted:
        return {}
    rows_of, key = _READS[level]
    rows = db.execute(
        select(
            key,
            func.coalesce(func.sum(M.inline_link_clicks), 0),
            func.coalesce(func.sum(M.results_reported), 0),
            func.coalesce(func.sum(M.impressions), 0),
        )
        .where(
            *cabinet_where(db, owner=owner, level=rows_of, account=EVERY_ACCOUNT),
            M.date >= date_range.since,
            M.date <= date_range.until,
            key.in_(wanted),
        )
        .group_by(key)
    )
    return {
        row[0]: Exact(
            link_clicks=int(row[1]), results=int(row[2]), impressions=int(row[3])
        )
        for row in rows
    }


def _reach(figures: Exact, people: People | None) -> int | None:
    """``None``: Meta was never asked about these days, which is not nobody."""
    if not figures.impressions:
        return 0
    if people is None or people.reach > figures.impressions:
        return None
    return people.reach


def _event_of(promoted: Mapping[str, Any] | None) -> str:
    if not isinstance(promoted, Mapping):
        return ""
    return str(promoted.get("custom_event_type") or "").strip().upper()


def shown_of(kind: str, adsets: Iterable[Any]) -> Shown:
    goal, promoted = campaign_goal(
        (
            row.external_id,
            row.optimization_goal_raw or "",
            row.promoted_object_raw
            if isinstance(row.promoted_object_raw, Mapping)
            else None,
        )
        for row in adsets
    )
    if not goal.strip() or kind in KEPT_KINDS:
        return Shown(kind=kind)
    counted = COUNTED_GOALS.get(goal.strip().upper())
    if counted is not None:
        return Shown(kind=counted, counts_events=True)
    outcome = screen_kind(goal, promoted)
    if outcome != "none":
        return Shown(kind=OUTCOME_KINDS.get(outcome, kind))
    if goal.strip().upper() != SITE_GOAL:
        return Shown(kind=UNCOUNTED_KIND)
    label = CONVERSION_LABELS.get(_event_of(promoted), CONVERSION_LABEL)
    return Shown(kind=CONVERSION_KIND, label=label, counts_events=True)


def _event_result(figures: Exact, spent: Money) -> tuple[int, Money | None]:
    cost = cost_per(MinorUnits(spent.minor), figures.results)
    if cost is None:
        return figures.results, None
    return figures.results, spent.model_copy(update={"minor": int(cost)})


def _manager_row(
    row: dict[str, Any], *, shown: Shown, figures: Exact, people: People | None
) -> None:
    row.update(
        kind=shown.kind,
        result_label=shown.label,
        clicks=figures.link_clicks,
        reach=_reach(figures, people),
    )
    if shown.counts_events and row["spent"] is not None:
        row["results"], row["unit_cost"] = _event_result(figures, row["spent"])


def _campaigns_by_id(db: Session, *, owner: User, ids: Iterable[str]) -> dict[str, Any]:
    wanted = frozenset(ids)
    if not wanted:
        return {}
    found = selectors.campaigns_for(db, owner=owner, external_ids=wanted)
    return {row.external_id: row for row in found}


def _by_account(campaigns: Iterable[Any]) -> dict[Any, list[Any]]:
    grouped: defaultdict[Any, list[Any]] = defaultdict(list)
    for campaign in campaigns:
        grouped[campaign.ad_account].append(campaign)
    return grouped


def _people(
    db: Session, *, owner: User, level: str, ids: Iterable[str], date_range: Range
) -> dict[str, People]:
    return people_counts(
        db,
        owner=owner,
        level=level,
        since=date_range.since,
        until=date_range.until,
        ids=list(ids),
    )


def _fill_level(
    db: Session,
    *,
    owner: User,
    level: str,
    rows: list[dict[str, Any]],
    date_range: Range,
    shown: Callable[[dict[str, Any]], Shown],
) -> None:
    ids = [row["id"] for row in rows]
    figures = _exact(db, owner=owner, level=level, ids=ids, date_range=date_range)
    people = _people(db, owner=owner, level=level, ids=ids, date_range=date_range)
    for row in rows:
        _manager_row(
            row,
            shown=shown(row),
            figures=figures.get(row["id"], Exact()),
            people=people.get(row["id"]),
        )


def manager_v2(db: Session, *, owner: User, ask: ListAsk) -> dict[str, Any]:
    out = manager(db, owner=owner, ask=ask)
    campaigns = _campaigns_by_id(
        db, owner=owner, ids=[row["id"] for row in out["campaigns"]]
    )
    groups = {
        group.external_id: group
        for campaign in campaigns.values()
        for group in campaign.adsets
    }

    def of_campaign(row: dict[str, Any]) -> Shown:
        campaign = campaigns.get(row["campaign_external_id"])
        adsets = campaign.adsets if campaign is not None else []
        return shown_of(row["kind"], adsets)

    def of_group(row: dict[str, Any]) -> Shown:
        group = groups.get(row["id"])
        return shown_of(row["kind"], [group] if group is not None else [])

    levels = (
        (MetricLevel.CAMPAIGN, out["campaigns"], of_campaign),
        (MetricLevel.ADSET, out["adsets"], of_group),
        (MetricLevel.AD, out["ads"], of_campaign),
    )
    for account, members in _by_account(campaigns.values()).items():
        chosen, _ = figures_range(db, owner=owner, account=account, ask=ask)
        here = {campaign.external_id for campaign in members}
        for level, rows, shown in levels:
            _fill_level(
                db,
                owner=owner,
                level=level,
                rows=[row for row in rows if row["campaign_external_id"] in here],
                date_range=chosen,
                shown=shown,
            )
    return out


def campaign_list_v2(db: Session, *, owner: User, ask: ListAsk) -> dict[str, Any]:
    out = campaign_list(db, owner=owner, ask=ask)
    rows = out["campaigns"]
    days = out["range"]
    chosen = Range(
        since=date.fromisoformat(days["since"]),
        until=date.fromisoformat(days["until"]),
        key=CUSTOM,
    )
    campaigns = _campaigns_by_id(
        db, owner=owner, ids=[row["external_id"] for row in rows]
    )
    figures = _exact(
        db,
        owner=owner,
        level=MetricLevel.CAMPAIGN,
        ids=campaigns,
        date_range=chosen,
    )
    for row in rows:
        campaign = campaigns.get(row["external_id"])
        shown = shown_of(row["kind"], campaign.adsets if campaign is not None else [])
        row.update(kind=shown.kind, result_label=shown.label)
        metrics = row["metrics"]
        if shown.counts_events and metrics is not None:
            metrics["results"], metrics["unit_cost"] = _event_result(
                figures.get(row["external_id"], Exact()), metrics["spent"]
            )
    return out


def tree_results_v2(
    db: Session, *, owner: User, campaign: Any, tree: dict[str, Any], date_range: Range
) -> dict[str, Any]:
    """The adverts of an event campaign count that event, like their campaign."""
    if not shown_of("", campaign.adsets).counts_events:
        return tree
    ads = [ad for group in tree["groups"] for ad in group["ads"]]
    figures = _exact(
        db,
        owner=owner,
        level=MetricLevel.AD,
        ids=[ad["external_id"] for ad in ads],
        date_range=date_range,
    )
    for ad in ads:
        if ad["spent"] is not None:
            ad["results"], ad["unit_cost"] = _event_result(
                figures.get(ad["external_id"], Exact()), ad["spent"]
            )
    return tree


def tree_range(db: Session, *, owner: User, campaign: Any, ask: ListAsk) -> Range:
    chosen: Range = figures_range(
        db, owner=owner, account=campaign.ad_account, ask=ask
    )[0]
    return chosen


__all__ = [
    "campaign_list_v2",
    "manager_v2",
    "shown_of",
    "tree_range",
    "tree_results_v2",
]
