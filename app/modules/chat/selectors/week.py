"""One completed week, read once and denominated in whatever the advertising bought."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from adskit import MinorUnits
from sqlalchemy import exists, select
from sqlalchemy.orm import Session, aliased

from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.chat.constants import BARREN_MIN_SPEND_PCT
from app.modules.chat.selectors.changes import active_days
from app.modules.chat.selectors.day_tables import DayCause, campaign_causes
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import EVERY_ACCOUNT
from app.modules.metrics.selectors.facts import Scope
from app.modules.metrics.selectors.results import screen_kind, sourced_label, words_for
from app.modules.metrics.selectors.scope import PageCampaigns
from core.chat.daily import NO_FIGURE, DayCampaign
from core.chat.report import CampaignLine, KindFigures, WeekFigures
from core.chat.results import RESULT_EN
from core.metrics import (
    DayFigures,
    Movement,
    Outcome,
    Totals,
    cost_per,
    movement,
    share,
)


def targets_of(
    db: Session, *, owner: User, ids: frozenset[str], names: dict[str, str]
) -> dict[str, str]:
    """Every provider id a change to this page could name, and whose it is."""
    found = {key: names.get(key, key) for key in ids}
    if ids:
        for group, campaign in db.execute(
            select(AdSet.external_id, Campaign.external_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(AdSet.owner_id == owner.id, Campaign.external_id.in_(list(ids)))
        ):
            found[group] = names.get(campaign, campaign)
        for advert, campaign in db.execute(
            select(Ad.external_id, Campaign.external_id)
            .join(AdSet, AdSet.id == Ad.adset_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(Ad.owner_id == owner.id, Campaign.external_id.in_(list(ids)))
        ):
            found[advert] = names.get(campaign, campaign)
    return {key: value for key, value in found.items() if key}


def spend_free_ids(db: Session, *, owner: User, page: PageCampaigns) -> set[str]:
    """This page's campaigns paid for out of an account nobody is watching."""
    from app.modules.integrations.selectors.watch import observed

    if not page.ids:
        return set()
    return set(
        db.scalars(
            select(Campaign.external_id)
            .join(AdAccount, AdAccount.id == Campaign.ad_account_id)
            .where(
                Campaign.owner_id == owner.id,
                Campaign.external_id.in_(list(page.ids)),
                AdAccount.is_active.is_(False),
                ~observed(),
            )
        )
    )


def sums_by_campaign(
    db: Session, *, owner: User, since: date, until: date, scope: Scope
) -> dict[str, Any]:
    from app.modules.metrics.selectors.facts import facts_by_campaign

    return facts_by_campaign(
        db, owner=owner, since=since, until=until, account=EVERY_ACCOUNT, scope=scope
    )


def campaign_mirror(db: Session, *, owner: User) -> dict[str, tuple[str, Outcome]]:
    """``{provider id: (name, what it was bought for)}`` from the mirror."""
    from app.modules.metrics.selectors.campaigns import goal_order

    speaker = (
        select(AdSet.id)
        .where(AdSet.owner_id == owner.id, AdSet.campaign_id == Campaign.id)
        .order_by(*goal_order())
        .limit(1)
        .scalar_subquery()
    )
    first = aliased(AdSet)
    rows = db.execute(
        select(
            Campaign.external_id,
            Campaign.name,
            first.optimization_goal_raw,
            first.promoted_object_raw,
        )
        .outerjoin(first, first.id == speaker)
        .where(Campaign.owner_id == owner.id)
    )
    return {
        external_id: (
            name or external_id,
            screen_kind(
                goal or "", promoted if isinstance(promoted, Mapping) else None
            ),
        )
        for external_id, name, goal, promoted in rows
    }


def week_campaigns(
    db: Session,
    *,
    owner: User,
    sums_now: dict[str, Any],
    sums_before: dict[str, Any],
    leads_now: dict[str, tuple[int, int]],
    leads_before: dict[str, tuple[int, int]],
    names: dict[str, str],
    kinds: dict[str, Outcome],
    currency: str,
    until: date,
) -> tuple[DayCampaign, ...]:
    """Every campaign that spent this week, the biggest spender first."""
    spent = sorted(
        (key for key, row in sums_now.items() if row.spend_minor > 0),
        key=lambda key: -sums_now[key].spend_minor,
    )
    states = _states(db, owner=owner, ids=spent)
    causes = campaign_causes(db, owner=owner, currency=currency, day=until)
    return tuple(
        _line(
            name=names.get(key, key),
            kind=kinds.get(key, "lead"),
            now=sums_now[key],
            before=sums_before.get(key),
            leads=(leads_now.get(key, (0, 0))[0], leads_before.get(key, (0, 0))[0]),
            state=states.get(key, ("", False)),
            cause=causes.get(key),
            currency=currency,
        )
        for key in spent
    )


def open_proposals(
    db: Session, *, owner: User, targets: dict[str, str], now: datetime
) -> int:
    """How many of the agent's proposals about this page wait for an answer."""
    from app.modules.agent.selectors import waiting

    return sum(
        1
        for row in waiting(db, owner=owner, now=now)
        if row.target_parent_id in targets or row.target_external_id in targets
    )


def _line(
    *,
    name: str,
    kind: Outcome,
    now: Any,
    before: Any,
    leads: tuple[int, int],
    state: tuple[str, bool],
    cause: DayCause | None,
    currency: str,
) -> DayCampaign:
    words = words_for(kind)
    count = count_for(kind=kind, sums=now, leads=leads[0])
    usual = count_for(kind=kind, sums=before, leads=leads[1])
    cost = cost_per(MinorUnits(now.spend_minor * words.per), count)
    usual_cost = (
        cost_per(MinorUnits(before.spend_minor * words.per), usual) if before else None
    )
    delivery, learning = state
    return DayCampaign(
        name=name,
        kind=kind,
        state=delivery,
        state_label=str(Delivery(delivery).label)
        if delivery in Delivery.values
        else "",
        learning=learning,
        spend=format_minor(amount_minor=now.spend_minor, currency=currency),
        results=count,
        result_label=sourced_label(kind),
        cost=_dash_or(cost, currency),
        cost_label=str(words.cost_label),
        usual_cost=_dash_or(usual_cost, currency),
        reported=int(getattr(now, "leads_reported", 0) or 0) if kind == "lead" else 0,
        spend_minor=now.spend_minor,
        cost_minor=cost,
        usual_cost_minor=usual_cost,
        cause=cause.cause if cause else "",
        cause_label=cause.label if cause else "",
        cause_line=cause.line if cause else "",
    )


def _states(db: Session, *, owner: User, ids: list[str]) -> dict[str, tuple[str, bool]]:
    if not ids:
        return {}
    group = aliased(AdSet)
    learning = exists().where(
        group.owner_id == owner.id,
        group.campaign_id == Campaign.id,
        group.is_learning.is_(True),
    )
    rows = db.execute(
        select(Campaign.external_id, Campaign.delivery, learning).where(
            Campaign.owner_id == owner.id, Campaign.external_id.in_(ids)
        )
    )
    return {key: (delivery or "", bool(flag)) for key, delivery, flag in rows}


def _dash_or(amount: int | None, currency: str) -> str:
    return (
        NO_FIGURE
        if amount is None
        else format_minor(amount_minor=amount, currency=currency)
    )


@dataclass(frozen=True, slots=True)
class KindTally:
    """What one kind of result cost and how much of it there was."""

    spend_minor: int = 0
    results: int = 0


def tallies(
    *,
    sums: dict[str, Any],
    kinds: dict[str, Outcome],
    leads: dict[str, tuple[int, int]],
) -> dict[Outcome, KindTally]:
    """The week split by what each campaign was bought for."""
    found: dict[Outcome, KindTally] = {}
    for key in set(sums) | set(leads):
        row = sums.get(key)
        kind = kinds.get(key, "lead")
        held = found.get(kind, KindTally())
        found[kind] = KindTally(
            spend_minor=held.spend_minor + (row.spend_minor if row else 0),
            results=held.results
            + count_for(kind=kind, sums=row, leads=leads.get(key, (0, 0))[0]),
        )
    return found


def cost_moves(
    *,
    now: dict[Outcome, KindTally],
    before: dict[Outcome, KindTally],
    kind: Outcome,
) -> dict[str, Movement]:
    """How the cost moved. Lower is better, which is the point."""
    return {
        "cpl": movement(
            now=_result_cost(now, kind),
            before=_result_cost(before, kind),
            lower_is_better=True,
        ),
    }


def _result_cost(tally: dict[Outcome, KindTally], kind: Outcome) -> int | None:
    words = words_for(kind)
    held = tally.get(kind, KindTally())
    return cost_per(MinorUnits(held.spend_minor * words.per), held.results)


def figures(
    days: list[DayFigures],
    *,
    totals: Totals,
    currency: str,
    kind: Outcome,
    tally: dict[Outcome, KindTally],
) -> WeekFigures:
    words = words_for(kind)
    return WeekFigures(
        spend=format_minor(amount_minor=totals.spend_minor, currency=currency),
        spend_minor=totals.spend_minor,
        qualified=totals.qualified,
        cpql=_money(totals.cpql_minor, currency),
        active_days=active_days(spend_by_day=[day.spend_minor for day in days]),
        kind=kind,
        results=tally.get(kind, KindTally()).results,
        result_cost=_money(_result_cost(tally, kind), currency),
        result_label=sourced_label(kind),
        result_cost_label=str(words.cost_label),
        kinds=_kinds(tally, currency=currency),
    )


def _kinds(
    tally: dict[Outcome, KindTally], *, currency: str
) -> tuple[KindFigures, ...]:
    countable = [
        (kind, held)
        for kind, held in tally.items()
        if words_for(kind).field and (held.spend_minor or held.results)
    ]
    return tuple(
        KindFigures(
            kind=kind,
            results=held.results,
            spend=format_minor(amount_minor=held.spend_minor, currency=currency),
            cost=_money(_result_cost(tally, kind), currency),
            label=sourced_label(kind),
            cost_label=str(words_for(kind).cost_label),
        )
        for kind, held in sorted(countable, key=lambda pair: -pair[1].spend_minor)
    )


def _money(amount: int | None, currency: str) -> str:
    """An amount, or an em dash where there is no answer."""
    return format_minor(amount_minor=amount, currency=currency) if amount else "—"


def week_kind(*, sums: dict[str, Any], kinds: dict[str, Outcome]) -> Outcome:
    """What this week's advertising was mostly bought for."""
    by_kind: dict[Outcome, int] = {}
    for key, row in sums.items():
        kind = kinds.get(key, "lead")
        by_kind[kind] = by_kind.get(kind, 0) + row.spend_minor
    if not by_kind:
        return "lead"
    return max(by_kind.items(), key=lambda pair: (pair[1], pair[0]))[0]


def spend_of(sums: dict[str, Any]) -> dict[str, int]:
    return {key: row.spend_minor for key, row in sums.items()}


def campaign_lines(
    *,
    leads: dict[str, tuple[int, int]],
    sums: dict[str, Any],
    names: dict[str, str],
    kinds: dict[str, Outcome],
    kind: Outcome,
    currency: str,
) -> tuple[CampaignLine | None, CampaignLine | None]:
    """The week's best campaign, and the one that took money for nothing."""
    keys = sorted(
        key for key in set(sums) | set(leads) if kinds.get(key, "lead") == kind
    )
    if len(keys) < 2:
        return None, None
    word = RESULT_EN.get(kind, RESULT_EN["lead"])[0].lower()
    spend = {key: spend_of(sums).get(key, 0) for key in keys}
    whole = sum(spend.values())
    rows = [
        (
            spend[key],
            CampaignLine(
                name=names.get(key, key),
                spend=format_minor(amount_minor=spend[key], currency=currency),
                leads=leads.get(key, (0, 0))[0],
                qualified=leads.get(key, (0, 0))[1],
                results=count_for(
                    kind=kind, sums=sums.get(key), leads=leads.get(key, (0, 0))[0]
                ),
                word=word,
                label=str(words_for(kind).one),
            ),
        )
        for key in keys
    ]
    best = max(rows, key=lambda pair: pair[1].results)[1]
    barren = max(
        (
            pair
            for pair in rows
            if not pair[1].results
            and share(part=pair[0], whole=whole) >= BARREN_MIN_SPEND_PCT
        ),
        key=lambda pair: pair[0],
        default=None,
    )
    return (best if best.results else None), (barren[1] if barren is not None else None)


def count_for(*, kind: Outcome, sums: Any, leads: int) -> int:
    """One campaign's count of the week's kind of result."""
    if kind == "lead":
        return leads
    column = words_for(kind).field
    return int(getattr(sums, column, 0) or 0) if sums and column else 0


__all__ = [
    "KindTally",
    "campaign_lines",
    "campaign_mirror",
    "cost_moves",
    "count_for",
    "figures",
    "open_proposals",
    "spend_free_ids",
    "spend_of",
    "sums_by_campaign",
    "tallies",
    "targets_of",
    "week_campaigns",
    "week_kind",
]
