from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from adskit import MinorUnits
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.leads.selectors import daily_counts
from app.modules.metrics.constants import EVERY_ACCOUNT, PERIOD_DAYS, MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.campaign_story import campaign_story
from app.modules.metrics.selectors.campaigns import campaign_goal_of
from app.modules.metrics.selectors.card_kinds import RESULT_KEYS, text_of
from app.modules.metrics.selectors.cards import (
    GROUP_TEXT,
    chosen_for,
    counts_range,
    day_note,
)
from app.modules.metrics.selectors.facts import People, cabinet_where, people_by_range
from app.modules.metrics.selectors.results import (
    OTHER_NOTE,
    screen_kind,
    uncounted_note,
    words_for,
)
from app.modules.metrics.selectors.shapes import (
    CampaignPanel,
    Card,
    CardGroupBlock,
    PanelPeriod,
)
from core.metrics import (
    GROUPS,
    CardKey,
    CardSpec,
    Outcome,
    PanelDay,
    PanelTotals,
    movement,
    newest_measured,
    panel_total,
    specs_for,
    with_provider_leads,
)

_SUMS: Final[dict[str, str]] = {
    "spend": "spend_minor",
    "impressions": "impressions",
    "clicks": "clicks",
    "link_clicks": "inline_link_clicks",
    "leads_reported": "leads_reported",
    "results": "results_reported",
    "recallers": "recallers",
    "profile_visits": "profile_visits",
    "video_plays": "video_plays",
    "video_thruplays": "video_thruplays",
    "reach": "reach",
    "unique_clicks": "unique_clicks",
}


@dataclass(frozen=True, slots=True)
class _Window:
    days: tuple[PanelDay, ...]
    now: PanelTotals
    before: PanelTotals


def campaign_panel(db: Session, *, owner: User, campaign: Any) -> CampaignPanel:
    keys = chosen_for(db, owner=owner)
    account = campaign.ad_account
    currency = account.currency or campaign.currency
    tzinfo = account.tzinfo()
    from app.common.db import utcnow

    today = utcnow().astimezone(tzinfo).date()
    widest = max(PERIOD_DAYS)
    since = today - timedelta(days=widest * 2 - 1)
    rows, has_people = _rows_for(db, owner=owner, campaign=campaign, since=since)
    leads = daily_counts(
        db,
        owner=owner,
        since=_start_of(since, tzinfo),
        until=_end_of(today, tzinfo),
        tzinfo=tzinfo,
        campaign_external_id=campaign.external_id,
    )
    goal, promoted = campaign_goal_of(db, owner=owner, campaign=campaign)
    kind = screen_kind(goal, promoted)
    span = tuple(
        _day(day=day, sums=rows.get(day), leads=leads.get(day), kind=kind)
        for day in _walk(since, today)
    )
    drawn = _drawable(keys, has_people=has_people, kind=kind)
    counted = people_by_range(
        db, owner=owner, level=MetricLevel.CAMPAIGN, external_id=campaign.external_id
    )
    return CampaignPanel(
        periods=tuple(
            _period(days=days, keys=drawn, currency=currency, kind=kind)
            for days in (
                _window(span, days=count, counted=counted) for count in PERIOD_DAYS
            )
        ),
        has_figures=any(row.is_measured or row.spend_minor for row in span[-widest:]),
        has_choice=bool(keys),
        note=uncounted_note(goal, promoted) or OTHER_NOTE if kind == "none" else "",
    )


def _rows_for(
    db: Session, *, owner: User, campaign: Any, since: date
) -> tuple[dict[date, dict[str, int]], bool]:
    own = _summed(
        db, owner=owner, campaign=campaign, since=since, level=MetricLevel.CAMPAIGN
    )
    if own:
        return (own, True)
    return (
        _summed(
            db, owner=owner, campaign=campaign, since=since, level=MetricLevel.ADSET
        ),
        False,
    )


def _summed(
    db: Session, *, owner: User, campaign: Any, since: date, level: str
) -> dict[date, dict[str, int]]:
    m = MetricsDaily
    rows = db.execute(
        select(
            m.date,
            *[
                func.coalesce(func.sum(getattr(m, column)), 0).label(name)
                for name, column in _SUMS.items()
            ],
        )
        .where(
            *cabinet_where(db, owner=owner, level=level, account=EVERY_ACCOUNT),
            m.campaign_external_id == campaign.external_id,
            m.date >= since,
        )
        .group_by(m.date)
    )
    return {row.date: {name: int(row._mapping[name]) for name in _SUMS} for row in rows}


def _day(
    *,
    day: date,
    sums: dict[str, int] | None,
    leads: tuple[int, int] | None,
    kind: Outcome = "lead",
) -> PanelDay:
    figures = sums or {}
    count, qualified = leads or (0, 0)
    built = PanelDay(
        day=day,
        spend_minor=MinorUnits(figures.get("spend", 0)),
        impressions=figures.get("impressions", 0),
        clicks=figures.get("clicks", 0),
        link_clicks=figures.get("link_clicks", 0),
        leads=count,
        qualified=qualified,
        leads_reported=figures.get("leads_reported", 0),
        received=count,
        results=figures.get("results", 0),
        recallers=figures.get("recallers", 0),
        profile_visits=figures.get("profile_visits", 0),
        video_plays=figures.get("video_plays", 0),
        video_thruplays=figures.get("video_thruplays", 0),
        reach=figures.get("reach", 0),
        unique_clicks=figures.get("unique_clicks", 0),
    )
    return with_provider_leads(built) if kind == "lead" else built


def _drawable(
    keys: tuple[CardKey, ...], *, has_people: bool, kind: Outcome = "lead"
) -> tuple[CardSpec, ...]:
    specs = specs_for(keys)
    if not words_for(kind).field:
        specs = tuple(spec for spec in specs if spec.key not in RESULT_KEYS)
    if has_people:
        return specs
    return tuple(spec for spec in specs if spec.basis != "day")


def _window(
    span: tuple[PanelDay, ...], *, days: int, counted: dict[tuple[date, date], People]
) -> _Window:
    now = span[-days:]
    earlier = span[-days * 2 : -days]
    return _Window(
        days=now,
        now=_with_people(panel_total(now), days=now, counted=counted),
        before=_with_people(panel_total(earlier), days=earlier, counted=counted),
    )


def _with_people(
    totals: PanelTotals,
    *,
    days: tuple[PanelDay, ...],
    counted: dict[tuple[date, date], People],
) -> PanelTotals:
    if not days:
        return totals
    people = counted.get((days[0].day, days[-1].day))
    if people is None:
        return totals
    return replace(totals, recallers=people.recallers, reach=people.reach)


def _period(
    *, days: _Window, keys: tuple[CardSpec, ...], currency: str, kind: Outcome = "lead"
) -> PanelPeriod:
    now = days.now
    latest = newest_measured(days.days)
    count = len(days.days)
    cards = {
        spec.key: _card(
            spec=spec,
            now=now,
            before=days.before,
            day=latest,
            currency=currency,
            kind=kind,
        )
        for spec in keys
    }
    story = campaign_story(days=days.days, currency=currency, kind=kind)
    return PanelPeriod(
        key=str(count),
        label="%(days)s kun" % {"days": count},
        groups=tuple(
            block
            for block in (
                _group(group=group, keys=keys, cards=cards) for group in GROUPS
            )
            if block is not None
        ),
        series=story.series,
        funnel=story.funnel,
        lid=story.lid,
        funnel_heading=story.heading,
        mismatch=story.mismatch,
    )


def _group(
    *, group: str, keys: tuple[CardSpec, ...], cards: dict[str, Card]
) -> CardGroupBlock | None:
    chosen = tuple(cards[spec.key] for spec in keys if spec.group == group)
    if not chosen:
        return None
    return CardGroupBlock(key=group, label=str(GROUP_TEXT[group]), cards=chosen)


def _card(
    *,
    spec: CardSpec,
    now: PanelTotals,
    before: PanelTotals,
    day: PanelDay | None,
    currency: str,
    kind: Outcome = "lead",
) -> Card:
    text = text_of(spec, kind=kind)
    moved = (
        movement(
            now=text.value(now),
            before=text.value(before),
            lower_is_better=spec.lower_is_better,
        )
        if text.value is not None
        else None
    )
    return Card(
        key=spec.key,
        label=str(text.label),
        hint=str(text.hint),
        display=text.display(now, day, currency),
        basis_note=day_note(day.day)
        if spec.basis == "day" and day and (not counts_range(spec.key, now))
        else "",
        delta_pct=moved.percent if moved else 0,
        trend=moved.direction if moved else "flat",
        is_good=moved.is_good if moved else False,
        value=_number(text.value(now)) if text.value is not None else None,
    )


def _number(found: float | None) -> float | None:
    return float(found) if found is not None else None


def _walk(since: date, until: date) -> list[date]:
    return [since + timedelta(days=step) for step in range((until - since).days + 1)]


def _start_of(day: date, tzinfo: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tzinfo)


def _end_of(day: date, tzinfo: ZoneInfo) -> datetime:
    return datetime.combine(day, time.max, tzinfo=tzinfo)


__all__ = ["campaign_panel"]
