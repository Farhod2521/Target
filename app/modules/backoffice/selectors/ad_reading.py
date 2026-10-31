"""One advert read whole: its figures over a window, and all that made it.

The list's row says what an advert did; this says how it was set up and how
the money moved. A campaign's figures belong to the campaign, so a launch that
shares one reads the shared figures and lists its neighbours in ``siblings``.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Final

from adskit import MinorUnits
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import DELIVERY_LABELS, LaunchStep
from app.modules.ads.models import Ad, AdSet, Campaign, CampaignLaunch
from app.modules.ads.selectors.launch_live import LaunchLive, launch_live
from app.modules.ads.selectors.launch_settings import (
    AudienceLines,
    LaunchSettings,
    audience_lines,
    launch_settings,
)
from app.modules.backoffice.selectors.advertising import (
    AdRow,
    AdWindow,
    launch_pairs,
    read_rows,
    result_kind,
)
from app.modules.backoffice.selectors.dashboard import (
    DAILY_UP_TO,
    DAY,
    MONTH,
    WEEK,
    WEEKLY_UP_TO,
    Window,
    bar_hint,
    bar_label,
)
from app.modules.leads.selectors import CampaignLeads, campaign_leads
from app.modules.leads.selectors.reads import (
    counts_by_ad,
    counts_by_adset,
    daily_counts,
)
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.selectors.campaigns import campaign_meta
from app.modules.metrics.selectors.facts import people_counts
from app.modules.metrics.selectors.panel import (
    AdFigures,
    CampaignFigures,
    FigureSums,
    campaign_figures,
)
from app.modules.metrics.selectors.results import ResultText, words_for
from core.metrics import cost_per

UNITS: Final[tuple[tuple[str, str], ...]] = (
    (DAY, "Kun"),
    (WEEK, "Hafta"),
    (MONTH, "Oy"),
)
# What ``ResultText.field`` is called on the figures read here.
FIELDS: Final[dict[str, str]] = {"results": "results_reported"}
LEAD_KIND: Final = "lead"
NO_GROUP: Final = "Guruhsiz"


@dataclass(frozen=True, slots=True)
class Result:
    """What the money bought over the window, in this advert's own words."""

    label: str
    count: int
    cost_minor: int | None
    cost_label: str
    note: str


@dataclass(frozen=True, slots=True)
class Bar:
    """One day, week or month of the window."""

    key: date
    label: str
    hint: str
    sums: FigureSums
    reach: int
    leads: int
    qualified: int
    results: int
    result_cost_minor: int | None


@dataclass(frozen=True, slots=True)
class AdLine:
    external_id: str
    name: str
    delivery_label: str
    quality_ranking: str
    sums: FigureSums
    leads: int
    lead_cost_minor: int | None


@dataclass(frozen=True, slots=True)
class GroupLine:
    external_id: str
    name: str
    delivery_label: str
    optimization_goal: str
    daily_budget_minor: int | None
    is_learning: bool
    problem: str
    audience: AudienceLines | None
    sums: FigureSums
    leads: int
    lead_cost_minor: int | None
    ads: tuple[AdLine, ...]


@dataclass(frozen=True, slots=True)
class Sibling:
    launch_id: uuid.UUID
    started_at: datetime


@dataclass(frozen=True, slots=True)
class AdReading:
    launch: CampaignLaunch
    window: AdWindow
    unit: str
    row: AdRow | None
    campaign: Campaign | None
    figures: CampaignFigures | None
    reach: int
    reach_is_exact: bool
    result: Result | None
    leads: int
    qualified: int
    lifetime: CampaignLeads | None
    bars: tuple[Bar, ...]
    groups: tuple[GroupLine, ...]
    siblings: tuple[Sibling, ...]
    settings: LaunchSettings
    live: LaunchLive


def owned_launch(
    db: Session, *, owner: User, launch_id: uuid.UUID
) -> CampaignLaunch | None:
    """This owner's launch; an id from another account's page answers nothing."""
    return db.scalar(
        select(CampaignLaunch)
        .options(joinedload(CampaignLaunch.page))
        .where(CampaignLaunch.owner_id == owner.id, CampaignLaunch.id == launch_id)
    )


def ad_reading(
    db: Session,
    *,
    owner: User,
    launch: CampaignLaunch,
    window: AdWindow,
    by: str = "",
) -> AdReading:
    settings = launch_settings(db, launch=launch)
    live = launch_live(db, launch=launch)
    pairs = launch_pairs([launch])
    if not pairs:
        return AdReading(
            launch=launch,
            window=window,
            unit=by if by in dict(UNITS) else DAY,
            row=None,
            campaign=None,
            figures=None,
            reach=0,
            reach_is_exact=False,
            result=None,
            leads=0,
            qualified=0,
            lifetime=None,
            bars=(),
            groups=(),
            siblings=(),
            settings=settings,
            live=live,
        )
    external_id = pairs[0][1]
    zone = launch.ad_account.tzinfo()
    since = datetime.combine(window.since, time.min, tzinfo=zone)
    until = datetime.combine(window.until, time.max, tzinfo=zone)
    figures = campaign_figures(
        db,
        owner=owner,
        provider=launch.provider,
        campaign_external_id=external_id,
        fall_back=True,
        since=window.since,
        until=window.until,
    )
    by_day = daily_counts(
        db,
        owner=owner,
        since=since,
        until=until,
        tzinfo=zone,
        campaign_external_id=external_id,
    )
    meta = campaign_meta(db, owner=owner, campaign_ids=frozenset({external_id})).get(
        external_id
    )
    kind = result_kind(meta)
    text = words_for(kind)
    unit, bars = _bars(
        figures=figures, by_day=by_day, window=window, by=by, kind=kind, text=text
    )
    people = people_counts(
        db,
        owner=owner,
        level=MetricLevel.CAMPAIGN,
        since=window.since,
        until=window.until,
        ids={external_id},
    ).get(external_id)
    leads = sum(count for count, _qualified in by_day.values())
    row = read_rows(
        db, owner=owner, pairs=pairs, since=window.since, until=window.until, zone=zone
    )[0]
    return AdReading(
        launch=launch,
        window=window,
        unit=unit,
        row=row,
        campaign=_campaign(db, owner=owner, external_id=external_id),
        figures=figures,
        reach=people.reach if people is not None else figures.widest_reach,
        reach_is_exact=people is not None,
        result=_result(
            sums=figures.total, leads=leads, kind=kind, text=text, note=row.note
        ),
        leads=leads,
        qualified=sum(qualified for _count, qualified in by_day.values()),
        lifetime=campaign_leads(
            db,
            owner=owner,
            provider=launch.provider,
            campaign_external_id=external_id,
            tzinfo=zone,
            limit=0,
        ),
        bars=bars,
        groups=_groups(
            db,
            owner=owner,
            external_id=external_id,
            figures=figures,
            by_group=counts_by_adset(db, owner=owner, since=since, until=until),
            by_ad=counts_by_ad(db, owner=owner, since=since, until=until),
        ),
        siblings=_siblings(db, launch=launch, external_id=external_id),
        settings=settings,
        live=live,
    )


def _count(sums: FigureSums, *, leads: int, kind: Any, text: ResultText) -> int:
    if kind == LEAD_KIND:
        return leads
    if not text.field:
        return 0
    return int(getattr(sums, FIELDS.get(text.field, text.field), 0) or 0)


def _cost(sums: FigureSums, *, count: int, text: ResultText) -> int | None:
    return cost_per(MinorUnits(sums.spend_minor * text.per), count)


def _result(
    *, sums: FigureSums, leads: int, kind: Any, text: ResultText, note: str
) -> Result:
    count = _count(sums, leads=leads, kind=kind, text=text)
    return Result(
        label=str(text.label) if text.field else "",
        count=count,
        cost_minor=_cost(sums, count=count, text=text),
        cost_label=str(text.cost_label),
        note=note,
    )


def _unit_for(days: int) -> str:
    return DAY if days <= DAILY_UP_TO else WEEK if days <= WEEKLY_UP_TO else MONTH


def _bars(
    *,
    figures: CampaignFigures,
    by_day: dict[date, tuple[int, int]],
    window: AdWindow,
    by: str,
    kind: Any,
    text: ResultText,
) -> tuple[str, tuple[Bar, ...]]:
    """The window cut into bars, oldest first; "all" starts at the first day
    anything happened, so ten empty years are not drawn."""
    days = {row.day: row for row in figures.days}
    active = sorted({*days, *by_day})
    start = active[0] if window.period == "all" and active else window.since
    span = (window.until - start).days + 1
    unit = by if by in dict(UNITS) else _unit_for(span)
    if not active:
        return unit, ()
    shape = Window(period=window.period, unit=unit, start=start, end=window.until)
    bars = []
    for first in shape.bars():
        last = shape.bar_end(first)
        inside = [day for day in active if first <= day <= last]
        sums = FigureSums()
        for day in inside:
            if day in days:
                sums = sums.plus(days[day].sums)
        leads = sum(by_day.get(day, (0, 0))[0] for day in inside)
        count = _count(sums, leads=leads, kind=kind, text=text)
        bars.append(
            Bar(
                key=first,
                label=bar_label(first, unit),
                hint=bar_hint(first, shape),
                sums=sums,
                reach=max(
                    (days[day].reach for day in inside if day in days), default=0
                ),
                leads=leads,
                qualified=sum(by_day.get(day, (0, 0))[1] for day in inside),
                results=count,
                result_cost_minor=_cost(sums, count=count, text=text),
            )
        )
    return unit, tuple(bars)


def _campaign(db: Session, *, owner: User, external_id: str) -> Campaign | None:
    return db.scalar(
        select(Campaign).where(
            Campaign.owner_id == owner.id, Campaign.external_id == external_id
        )
    )


def _spent(sums: FigureSums, leads: int) -> int | None:
    return cost_per(MinorUnits(sums.spend_minor), leads)


def _ad_line(
    *,
    external_id: str,
    ad: Ad | None,
    figures: AdFigures | None,
    by_ad: dict[str, tuple[int, int]],
) -> AdLine:
    sums = figures.sums if figures is not None else FigureSums()
    leads = by_ad.get(external_id, (0, 0))[0]
    return AdLine(
        external_id=external_id,
        name=(ad.name if ad is not None else "")
        or (figures.name if figures is not None else ""),
        delivery_label=str(DELIVERY_LABELS.get(ad.delivery, ad.delivery))
        if ad is not None
        else "",
        quality_ranking=figures.quality_ranking if figures is not None else "",
        sums=sums,
        leads=leads,
        lead_cost_minor=_spent(sums, leads),
    )


def _groups(
    db: Session,
    *,
    owner: User,
    external_id: str,
    figures: CampaignFigures,
    by_group: dict[str, tuple[int, int]],
    by_ad: dict[str, tuple[int, int]],
) -> tuple[GroupLine, ...]:
    """Every ad group and advert, with what each did over the window."""
    adsets = list(
        db.scalars(
            select(AdSet)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(AdSet.owner_id == owner.id, Campaign.external_id == external_id)
            .order_by(AdSet.created_at)
        )
    )
    ads = list(
        db.scalars(
            select(Ad)
            .where(Ad.adset_id.in_([row.id for row in adsets]))
            .order_by(Ad.created_at)
        )
    )
    numbers = {row.external_id: row for row in figures.groups}
    ad_numbers = {row.external_id: row for row in figures.ads}
    lines = []
    for adset in adsets:
        sums = (
            numbers[adset.external_id].sums
            if adset.external_id in numbers
            else FigureSums()
        )
        leads = by_group.get(adset.external_id, (0, 0))[0]
        lines.append(
            GroupLine(
                external_id=adset.external_id,
                name=adset.name,
                delivery_label=str(DELIVERY_LABELS.get(adset.delivery, adset.delivery)),
                optimization_goal=adset.optimization_goal_raw,
                daily_budget_minor=adset.daily_budget_minor,
                is_learning=adset.is_learning,
                problem=adset.issue_summary,
                audience=audience_lines(adset.targeting_raw),
                sums=sums,
                leads=leads,
                lead_cost_minor=_spent(sums, leads),
                ads=tuple(
                    _ad_line(
                        external_id=ad.external_id,
                        ad=ad,
                        figures=ad_numbers.get(ad.external_id),
                        by_ad=by_ad,
                    )
                    for ad in ads
                    if ad.adset_id == adset.id
                ),
            )
        )
    return (*lines, *_gone(figures=figures, ads=ads, by_ad=by_ad))


def _gone(
    *,
    figures: CampaignFigures,
    ads: list[Ad],
    by_ad: dict[str, tuple[int, int]],
) -> tuple[GroupLine, ...]:
    """Adverts with figures the mirror no longer has: the money is still real."""
    known = {ad.external_id for ad in ads}
    left = [row for row in figures.ads if row.external_id not in known]
    if not left:
        return ()
    lines = tuple(
        _ad_line(external_id=row.external_id, ad=None, figures=row, by_ad=by_ad)
        for row in left
    )
    sums = FigureSums()
    for row in left:
        sums = sums.plus(row.sums)
    leads = sum(line.leads for line in lines)
    return (
        GroupLine(
            external_id="",
            name=NO_GROUP,
            delivery_label="",
            optimization_goal="",
            daily_budget_minor=None,
            is_learning=False,
            problem="",
            audience=None,
            sums=sums,
            leads=leads,
            lead_cost_minor=_spent(sums, leads),
            ads=lines,
        ),
    )


def _siblings(
    db: Session, *, launch: CampaignLaunch, external_id: str
) -> tuple[Sibling, ...]:
    """The other launches building into the same campaign, newest first."""
    rows = db.execute(
        select(
            CampaignLaunch.id,
            CampaignLaunch.created_refs,
            CampaignLaunch.delivery_started_at,
            CampaignLaunch.finished_at,
            CampaignLaunch.created_at,
        ).where(
            CampaignLaunch.owner_id == launch.owner_id,
            CampaignLaunch.id != launch.id,
        )
    )
    found = [
        Sibling(
            launch_id=row.id,
            started_at=row.delivery_started_at or row.finished_at or row.created_at,
        )
        for row in rows
        if external_id in ref_field.ref_ids(row.created_refs or {}, LaunchStep.CAMPAIGN)
    ]
    return tuple(sorted(found, key=lambda row: row.started_at, reverse=True))
