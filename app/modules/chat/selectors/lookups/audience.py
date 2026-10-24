"""One ad group's audience: its settings by name, and where its money went."""

from datetime import date, datetime
from typing import Final

from adskit import MinorUnits
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.models import AdSet, Campaign
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.agent.figures import decimal_of
from app.modules.chat.selectors.briefs import delivery_label
from app.modules.chat.selectors.lookups.common import (
    in_subscription,
    money,
    named,
    origin,
    refused,
    section,
    window,
)
from app.modules.chat.selectors.lookups.sums import figures_by, leads_by
from app.modules.metrics.constants import NIGHTLY_BREAKDOWNS, BreakdownKind
from app.modules.metrics.models import MetricsBreakdown
from core.agent.funnel import per_ten_thousand
from core.chat.lookups import SLICE_ROWS, AdSetLookup
from core.metrics import SegmentFigures, compare_segments, counts_leads, split_segment
from core.targeting.spelled import AudienceWords, Place, spell

GENDER_WORDS: Final = {"male": "men", "female": "women"}

BARREN: Final = "had its chance and brought no leads"
WEAK: Final = "a few leads, too few to compare"
THIN: Final = "too little spend to judge"


def audience_details(
    db: Session, *, owner: User, arguments: AdSetLookup, scope: PageScope, now: datetime
) -> str:
    """Who the group is shown to, and how its money split across that."""
    group = db.scalar(
        select(AdSet)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .where(
            AdSet.owner_id == owner.id,
            in_subscription(Campaign.ad_account_id),
            AdSet.external_id == arguments.adset_id,
        )
        .limit(1)
    )
    if group is None:
        return (
            f"No ad group with id {arguments.adset_id} in the subscription. "
            "Use campaign_details or find to get its id."
        )
    if not scope.allows_adset(group.external_id):
        return refused(
            scope=scope, kind="ad group", level="adset", external_id=group.external_id
        )
    since, until = window(db, owner=owner, days=arguments.days)
    made = origin(scope, level="adset", external_id=group.external_id)
    lines = [
        *_settings(group, spell(group.targeting_raw)),
        *([f"- {made.removeprefix(' - ')}"] if made else []),
        "",
        *_totals(db, owner=owner, group=group, since=since, until=until),
    ]
    lines += ["", *_splits(db, owner=owner, group=group, since=since, until=until)]
    return "\n".join(lines)


def _settings(group: AdSet, words: AudienceWords) -> list[str]:
    campaign = group.campaign
    state = str(delivery_label(group.delivery))
    if group.is_learning:
        state += ", still learning"
    lines = [
        f"## Who ad group {named(group.name, group.external_id)} "
        f"(id {group.external_id}) is shown to",
        f"- campaign {named(campaign.name, campaign.external_id)} - {state}",
        f"- places: {_places(words.places) or 'not set'}",
    ]
    if words.excluded_places:
        lines.append(f"- excluded places: {_places(words.excluded_places)}")
    lines.append(f"- ages: {_ages(words)}")
    lines.append(f"- genders: {GENDER_WORDS.get(words.genders, 'everyone')}")
    lines += [
        f"- {'and must also match' if index else 'interests'} (any of): "
        + ", ".join(block)
        for index, block in enumerate(words.detailed)
    ] or ["- interests: none, the audience is not narrowed by interests"]
    if words.excluded_detailed:
        lines.append(f"- excluded interests: {', '.join(words.excluded_detailed)}")
    if words.own_lists:
        lines.append(f"- saved audiences: {', '.join(words.own_lists)}")
    if words.excluded_lists:
        lines.append(f"- saved audiences left out: {', '.join(words.excluded_lists)}")
    if words.is_automatic:
        lines.append("- the provider may widen the audience past these settings")
    lines.append(f"- placements: {_placements(words)}")
    return lines


def _totals(
    db: Session, *, owner: User, group: AdSet, since: date, until: date
) -> list[str]:
    ids, column = [group.external_id], "adset_external_id"
    figures = figures_by(
        db, owner=owner, column=column, ids=ids, since=since, until=until
    )
    own = figures.get(group.external_id, {})
    received = leads_by(
        db, owner=owner, column=column, ids=ids, since=since, until=until
    )
    currency = group.campaign.currency
    parts = [
        f"spend {money(int(own.get('spend') or 0), currency)}",
        f"shown {int(own.get('shown') or 0)}",
        f"link clicks {int(own.get('link_clicks') or 0)}",
        f"leads received {received.get(group.external_id, 0)}",
        f"provider counted leads {int(own.get('reported') or 0)}",
    ]
    if group.daily_budget_minor:
        parts.insert(0, f"daily budget {money(group.daily_budget_minor, currency)}")
    return [f"## The group, {since} to {until}", "- " + ", ".join(parts)]


def _splits(
    db: Session, *, owner: User, group: AdSet, since: date, until: date
) -> list[str]:
    lines = [
        "## Where the money went",
        "- by the provider's own lead counts: a lead received here carries "
        "no age, region or placement",
    ]
    judged = counts_leads(group.optimization_goal_raw or "")
    if not judged:
        lines.append(
            "- this group is not optimised for leads, so slices carry no verdict"
        )
    for kind in NIGHTLY_BREAKDOWNS:
        cut = _cut(db, owner=owner, group=group, kind=kind, since=since, until=until)
        lines += [
            "",
            *section(
                str(BreakdownKind(kind).label),
                _slice_lines(cut, judged=judged, currency=group.campaign.currency),
                empty="no figures for this cut yet",
            ),
        ]
    return lines


def _cut(
    db: Session, *, owner: User, group: AdSet, kind: str, since: date, until: date
) -> list[SegmentFigures]:
    from app.modules.metrics.selectors.segments import breakdown_where

    b = MetricsBreakdown
    rows = db.execute(
        select(
            b.breakdown_value,
            func.sum(b.spend_minor),
            func.sum(b.impressions),
            func.sum(b.clicks),
            func.sum(b.leads_reported),
        )
        .where(
            *breakdown_where(
                db, owner=owner, kind=kind, account=group.campaign.ad_account
            ),
            b.external_id == group.external_id,
            b.date >= since,
            b.date <= until,
        )
        .group_by(b.breakdown_value)
    )
    return [
        SegmentFigures(
            segment=str(value),
            spend_minor=MinorUnits(int(spend or 0)),
            impressions=int(impressions or 0),
            clicks=int(clicks or 0),
            leads_reported=int(leads or 0),
        )
        for value, spend, impressions, clicks, leads in rows
    ]


def _slice_lines(
    cut: list[SegmentFigures], *, judged: bool, currency: str
) -> list[str]:
    comparison = compare_segments(cut)
    verdicts = {item.segment: _compared(item.cpl_index) for item in comparison.ranked}
    verdicts |= {item.segment: BARREN for item in comparison.barren}
    verdicts |= {item.segment: WEAK for item in comparison.weak}
    verdicts |= {item.segment: THIN for item in comparison.thin}
    shares = {
        item.segment: item
        for item in (
            *comparison.ranked,
            *comparison.barren,
            *comparison.weak,
            *comparison.thin,
        )
    }
    lines = []
    for row in sorted(cut, key=lambda item: -item.spend_minor)[:SLICE_ROWS]:
        cost = shares[row.segment]
        rate = per_ten_thousand(part=row.clicks, whole=row.impressions)
        line = (
            f"- {_label(row.segment)}: spend {money(row.spend_minor, currency)} "
            f"({cost.spend_share}% of this cut), shown {row.impressions}, "
            f"clicks per 1000 shown {decimal_of(rate, 10) if rate is not None else 0}"
        )
        if judged:
            line += f", provider leads {row.leads_reported}"
            if cost.cpl_reported_minor is not None:
                line += f", cost per lead {money(cost.cpl_reported_minor, currency)}"
            line += f" [{verdicts[row.segment]}]"
        lines.append(line)
    return lines


def _compared(index: int | None) -> str:
    if index is None or index == 100:
        return "enough leads to compare: about the group's average"
    if index < 100:
        return f"enough leads to compare: {100 - index}% cheaper than average"
    return f"enough leads to compare: {index - 100}% dearer than average"


def _label(value: str) -> str:
    from app.modules.metrics.selectors.dashboard import SEGMENT_LABELS

    return " · ".join(
        str(SEGMENT_LABELS.get(part, part.replace("_", " ")))
        for part in split_segment(value)
    )


def _places(places: tuple[Place, ...]) -> str:
    return ", ".join(
        f"{place.name} (within {place.radius} {place.unit or 'km'})"
        if place.radius
        else place.name
        for place in places
    )


def _ages(words: AudienceWords) -> str:
    low, high = words.age_min, words.age_max
    if low and high:
        return f"{low}-{high}"
    if low:
        return f"{low} and older"
    if high:
        return f"up to {high}"
    return "any"


def _placements(words: AudienceWords) -> str:
    if not words.placements:
        chosen = "chosen automatically by the provider"
    else:
        chosen = "; ".join(
            f"{platform}: {', '.join(positions) if positions else 'all positions'}"
            for platform, positions in words.placements
        )
    if words.devices:
        chosen += f" (devices: {', '.join(words.devices)})"
    return chosen


__all__ = ["audience_details"]
