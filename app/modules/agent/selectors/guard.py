"""Every running group's day so far, as the half-hourly guard reads it.

Today's figures in the account's own clock, the group's usual level, and
what the rules need beside them: whether it was launched from here, how
long ago, whether it still learns, whether its page opens, its adverts.

**The usual level is the group's own.** Its last fourteen finished days,
their middle day - :func:`core.agent.usual.usual_level`, the price and the
click rate and the showings' price together. A group without five such
days is held against its own first days: their pooled price up to its last
result, once they brought three - a price only, so such a group is judged
on its price and not on its rates. Never against another group: the
account's other lead adverts sell other things, at other prices. A group
with no price yet is held against its day's budget.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.agent.selectors.same_day import (
    RESULT_COLUMNS,
    adset_sums,
    kind_of,
)
from app.modules.agent.selectors.window import start_of
from app.modules.integrations.models import AdAccount, PageAccount
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.facts import cabinet_where
from core.agent.guard import START_RESULTS, AdToday, GroupToday, Usual
from core.agent.usual import DayFigures, usual_level
from core.metrics import Outcome, heard_leads

# What one result is, for the kinds whose price today means something: the
# same-day kinds without the recall, which has a reach and not a price.
GUARD_KINDS: Final = frozenset({"lead", "click", "chat", "call", "profile"})
USUAL_DAYS: Final = 14
# The figures a group's count restarts from, by their names in a baseline.
COUNTED: Final = ("spend_minor", "results", "impressions", "link_clicks")


@dataclass(frozen=True, slots=True)
class Guarded:
    """One running group, ready for the rules, with what a message needs."""

    group: GroupToday
    account: AdAccount
    name: str
    campaign_external_id: str
    kind: Outcome
    day: date
    # The pages of its adverts that did not open at the last look.
    down_urls: tuple[str, ...] = ()
    # Where it sits, for the owner to find it: the Facebook page it speaks
    # for and its campaign, by name.
    page_name: str = ""
    campaign_name: str = ""

    @property
    def currency(self) -> str:
        return str(self.account.currency)


def guarded_groups(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    now: datetime,
    baselines: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[Guarded]:
    """This account's running groups of a priced kind, each with its day.

    ``baselines`` is ``{group: the figures its count restarts from}`` - a
    group stopped today and switched back on is judged on what it spends
    and brings from then, never again on the money that stopped it. One
    applies only on the day it names.
    """
    from app.modules.agent.selectors.account_reads import landing_by_adset
    from app.modules.agent.selectors.launch_watch import switched_on
    from app.modules.agent.selectors.week_frequency import week_readings
    from app.modules.leads.selectors import counts_by_adset

    tzinfo = account.tzinfo()
    today = now.astimezone(tzinfo).date()
    rows = [
        (row, kind)
        for row in db.scalars(
            select(AdSet)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(
                AdSet.owner_id == owner.id,
                Campaign.ad_account_id == account.id,
                AdSet.delivery == Delivery.ACTIVE,
            )
            .order_by(AdSet.name)
        )
        if (kind := kind_of(row.optimization_goal_raw, row.promoted_object_raw))
        in GUARD_KINDS
    ]
    if not rows:
        return []
    ids = [row.external_id for row, _kind in rows]
    kinds = {row.external_id: kind for row, kind in rows}
    born = switched_on(db, owner=owner, account=account)
    sums = adset_sums(db, owner=owner, account=account, since=today, until=today)
    heard = counts_by_adset(db, owner=owner, since=start_of(today, tzinfo), until=now)
    history = _days(db, owner=owner, account=account, kinds=kinds, today=today)
    own = _own_usuals(history)
    landings = landing_by_adset(db, owner=owner, account=account)
    weeks = week_readings(db, owner=owner, account=account, adset_ids=ids)
    adverts = _adverts(db, owner=owner, account=account, kinds=kinds, today=today)
    page_names = _page_names(db, owner=owner, adset_ids=ids)
    found: list[Guarded] = []
    for row, kind in rows:
        figures = sums.get(row.external_id, {})
        results = _results(kind, figures, heard.get(row.external_id, (0, 0))[0])
        counted = _since_baseline(
            {
                "spend_minor": figures.get("spend_minor", 0),
                "results": results,
                "impressions": figures.get("impressions", 0),
                "link_clicks": figures.get("inline_link_clicks", 0),
            },
            (baselines or {}).get(row.external_id),
            today=today,
        )
        past = history.get(row.external_id, {})
        usual = own.get(row.external_id) or _start_usual(past)
        dry_spend, dry_days = _dry(
            past,
            today=today,
            spent_today=counted["spend_minor"],
            results_today=counted["results"],
            since=_dry_floor(
                born.get(row.external_id) or row.start_time,
                (baselines or {}).get(row.external_id),
                tzinfo=tzinfo,
                # Against its day's budget the first day's money counts too.
                first_day=not usual.cost_minor,
            ),
        )
        week = weeks.get(row.external_id)
        landing = landings.get(row.external_id)
        found.append(
            Guarded(
                group=GroupToday(
                    adset_id=row.external_id,
                    ours=row.external_id in born,
                    hours_running=_hours(row, born=born, now=now),
                    learning=bool(row.is_learning),
                    site_down=bool(landing is not None and landing.down_urls),
                    own_budget=bool(row.daily_budget_minor),
                    frequency=week.frequency if week is not None else None,
                    usual=usual,
                    ads=tuple(adverts.get(row.external_id, ())),
                    dry_spend_minor=dry_spend,
                    dry_days=dry_days,
                    day_budget_minor=_day_budget(row),
                    past_results=sum(day.results for day in past.values()),
                    **counted,
                ),
                account=account,
                name=row.name or row.external_id,
                campaign_external_id=(
                    row.campaign.external_id if row.campaign is not None else ""
                ),
                kind=kind,
                day=today,
                down_urls=tuple(landing.down_urls) if landing is not None else (),
                page_name=page_names.get(row.external_id, ""),
                campaign_name=(
                    (row.campaign.name or row.campaign.external_id)
                    if row.campaign is not None
                    else ""
                ),
            )
        )
    return found


def _page_names(db: Session, *, owner: User, adset_ids: list[str]) -> dict[str, str]:
    """``{group: its Facebook page's name}``; the page's id where the page is
    not one of the owner's connected ones, nothing where none is known."""
    from app.modules.ads.selectors.pages import pages_by_adset

    pages = pages_by_adset(db, owner=owner, adset_ids=adset_ids)
    if not pages:
        return {}
    names = dict(
        db.execute(
            select(PageAccount.external_id, PageAccount.name).where(
                PageAccount.owner_id == owner.id,
                PageAccount.external_id.in_(set(pages.values())),
            )
        ).all()
    )
    return {group: names.get(page) or page for group, page in pages.items()}


def _hours(row: AdSet, *, born: Mapping[str, datetime], now: datetime) -> float | None:
    """Hours since the switch-on: ours by the launch, another's by its start."""
    since = born.get(row.external_id) or row.start_time
    if since is None:
        return None
    return max(0.0, (now - since).total_seconds() / 3600)


def _results(kind: Outcome, figures: Mapping[str, int], ours: int) -> int:
    """A lead either side has seen, or the provider's count of the kind."""
    if kind == "lead":
        return heard_leads(ours=ours, reported=_reported(kind, figures))
    return _reported(kind, figures)


def _reported(kind: Outcome, figures: Mapping[str, int]) -> int:
    if kind == "lead":
        return max(
            int(figures.get("leads_reported", 0) or 0),
            int(figures.get("results_reported", 0) or 0),
        )
    return int(figures.get(RESULT_COLUMNS[kind], 0) or 0)


def _since_baseline(
    counted: dict[str, int], baseline: Mapping[str, Any] | None, *, today: date
) -> dict[str, int]:
    if not baseline or baseline.get("day") != today.isoformat():
        return counted
    return {
        name: max(0, counted[name] - int(baseline.get(name, 0) or 0))
        for name in COUNTED
    }


def _day_budget(row: AdSet) -> int:
    """The day's budget: the group's own, else its campaign's shared one."""
    shared = row.campaign.daily_budget_minor if row.campaign is not None else 0
    return int(row.daily_budget_minor or shared or 0)


def _start_usual(days: Mapping[date, DayFigures]) -> Usual:
    """A new group's own price: its finished days pooled, up to the last one
    that brought a result - the dry days after it are what is being judged,
    and would raise the very price they are held against."""
    spent = results = 0
    pooled: tuple[int, int] | None = None
    for day in sorted(days):
        spent += days[day].spend_minor
        results += days[day].results
        if days[day].results > 0:
            pooled = (spent, results)
    if pooled is None or pooled[1] < START_RESULTS or pooled[0] <= 0:
        return Usual()
    return Usual(cost_minor=max(1, pooled[0] // pooled[1]), source="start")


_DAY_COLUMNS: Final = (
    "spend_minor",
    "impressions",
    "inline_link_clicks",
    "leads_reported",
    "results_reported",
    "profile_visits",
)


DRY_DAYS: Final = 7


def _days(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    kinds: Mapping[str, Outcome],
    today: date,
) -> dict[str, dict[date, DayFigures]]:
    """``{group: {finished day: its figures}}`` over the last fortnight."""
    m = MetricsDaily
    rows = db.execute(
        select(
            m.adset_external_id,
            m.date,
            *(func.sum(getattr(m, column)).label(column) for column in _DAY_COLUMNS),
        )
        .where(
            *cabinet_where(db, owner=owner, account=account),
            m.adset_external_id.in_(list(kinds)),
            m.date >= today - timedelta(days=USUAL_DAYS),
            m.date < today,
        )
        .group_by(m.adset_external_id, m.date)
    ).mappings()
    days: dict[str, dict[date, DayFigures]] = defaultdict(dict)
    for row in rows:
        figures = {column: int(row[column] or 0) for column in _DAY_COLUMNS}
        days[row["adset_external_id"]][row["date"]] = DayFigures(
            spend_minor=figures["spend_minor"],
            impressions=figures["impressions"],
            link_clicks=figures["inline_link_clicks"],
            results=_reported(kinds[row["adset_external_id"]], figures),
        )
    return days


def _own_usuals(history: Mapping[str, Mapping[date, DayFigures]]) -> dict[str, Usual]:
    """``{group: its own fortnight's middle day}``, for those that have one."""
    found: dict[str, Usual] = {}
    for adset_id, group_days in history.items():
        usual = usual_level(list(group_days.values()))
        if usual.cost_minor:
            found[adset_id] = Usual(
                cost_minor=usual.cost_minor,
                link_ctr_bp=usual.link_ctr_bp,
                cpm_minor=usual.cpm_minor,
                source="own",
            )
    return found


def _dry_floor(
    started: datetime | None,
    baseline: Mapping[str, Any] | None,
    *,
    tzinfo: Any,
    first_day: bool = False,
) -> date | None:
    """The first day a dry spell may count: the day after the switch-on -
    the switch-on's own day with ``first_day`` - and never a day a stop of
    ours already answered for."""
    floor = (
        started.astimezone(tzinfo).date() + timedelta(days=0 if first_day else 1)
        if started is not None
        else None
    )
    stopped = str((baseline or {}).get("day") or "")
    if stopped:
        after = date.fromisoformat(stopped) + timedelta(days=1)
        floor = max(floor, after) if floor is not None else after
    return floor


def _dry(
    days: Mapping[date, DayFigures],
    *,
    today: date,
    spent_today: int,
    results_today: int,
    since: date | None,
) -> tuple[int, int]:
    """The money gone since the last result, and over how many days: today,
    then back day by day while a day brought nothing, a week at most."""
    if results_today > 0:
        return 0, 1
    spent, counted = spent_today, 1
    for back in range(1, DRY_DAYS):
        day = today - timedelta(days=back)
        if since is not None and day < since:
            break
        figures = days.get(day)
        if figures is None or figures.spend_minor <= 0:
            continue
        if figures.results > 0:
            break
        spent += figures.spend_minor
        counted = back + 1
    return spent, counted


def _adverts(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    kinds: Mapping[str, Outcome],
    today: date,
) -> dict[str, list[AdToday]]:
    """``{group: its adverts' day so far}``, by the provider's own counts."""
    m = MetricsDaily
    rows = list(
        db.execute(
            select(
                m.adset_external_id,
                m.ad_external_id,
                func.max(m.object_name).label("name"),
                *(
                    func.sum(getattr(m, column)).label(column)
                    for column in _DAY_COLUMNS
                ),
            )
            .where(
                *cabinet_where(db, owner=owner, level=MetricLevel.AD, account=account),
                m.adset_external_id.in_(list(kinds)),
                m.date == today,
                m.ad_external_id != "",
            )
            .group_by(m.adset_external_id, m.ad_external_id)
        ).mappings()
    )
    live = set(
        db.scalars(
            select(Ad.external_id).where(
                Ad.owner_id == owner.id,
                Ad.external_id.in_([row["ad_external_id"] for row in rows]),
                Ad.delivery == Delivery.ACTIVE,
            )
        )
    )
    found: dict[str, list[AdToday]] = defaultdict(list)
    for row in rows:
        figures = {column: int(row[column] or 0) for column in _DAY_COLUMNS}
        found[row["adset_external_id"]].append(
            AdToday(
                ad_id=row["ad_external_id"],
                name=row["name"] or "",
                spend_minor=figures["spend_minor"],
                results=_reported(kinds[row["adset_external_id"]], figures),
                live=row["ad_external_id"] in live,
            )
        )
    return found


def fresh(db: Session, *, owner: User, account: AdAccount, now: datetime) -> bool:
    """Whether the account and its today's figures were read within the hour:
    a stop on an hour-old reading is a stop on a guess."""
    from app.modules.agent.constants import AUTO_STOP_FRESH_MINUTES

    since = now - timedelta(minutes=AUTO_STOP_FRESH_MINUTES)
    if account.synced_at is None or account.synced_at < since:
        return False
    today = now.astimezone(account.tzinfo()).date()
    newest = db.scalar(
        select(func.max(MetricsDaily.synced_at)).where(
            *cabinet_where(db, owner=owner, account=account),
            MetricsDaily.date == today,
        )
    )
    return newest is not None and newest >= since


__all__ = [
    "COUNTED",
    "GUARD_KINDS",
    "USUAL_DAYS",
    "Guarded",
    "fresh",
    "guarded_groups",
]
