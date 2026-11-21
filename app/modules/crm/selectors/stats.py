"""What one pair's CRM did with the leads of a period, and what they cost.

Every figure is counted over one cohort: the cards whose enquiry came in
the period. A lead of the 3rd sold on the 20th is a sale of the 3rd's
leads, so leads, quality, sales and conversion always describe the same
people and conversion can never pass 100%. Only ``open`` and ``late``
are the board as it stands now.

The cohort is set against the advertising that fed it: the period's spend
of the adverts this CRM takes leads from (:func:`spend_rows`), read in the
CRM's currency. The counts are kept as :class:`core.metrics.sales.SalesFigures`
- for the whole period and for each manager, advert, campaign and day - and
every metric on them is :func:`core.metrics.sales.answers`. Days are the ad
account's own, so a lead stands on the same day as the spend that brought
it.
"""

import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any, Final

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.common.dates import localtime, office_zone
from app.modules.accounts.models import User
from app.modules.crm.constants import SetupState, StageKind
from app.modules.crm.models import CrmCard, CrmSetup, CrmStage
from app.modules.crm.selectors import Scope, Viewer, holds, setup_of, stages_of
from app.modules.crm.selectors.money import Pricer
from app.modules.integrations.models import AdAccount
from app.modules.leads.constants import MANUAL_PROVIDER
from app.modules.leads.models import Lead
from core.metrics.sales import Completeness, SalesFigures, completeness

PERIODS: Final = {"today": 1, "7": 7, "30": 30, "90": 90}
DEFAULT_DAYS: Final = 30
# The longest typed range: a year and a day, so «last year to today» fits.
MAX_DAYS: Final = 367
ADS_SHOWN: Final = 20
CAMPAIGNS_SHOWN: Final = 20
REASONS_SHOWN: Final = 8


@dataclass(frozen=True, slots=True)
class Range:
    since: date
    until: date
    today: date
    earliest: date
    # Whose days these are: the ad account's, so a lead and the spend that
    # brought it fall on the same one. The office's where there is no pair.
    zone: tzinfo | None = None

    @property
    def days(self) -> int:
        return (self.until - self.since).days + 1

    def bounds(self) -> tuple[datetime, datetime]:
        zone = self.zone or office_zone()
        start = datetime.combine(self.since, time.min).replace(tzinfo=zone)
        end = datetime.combine(self.until + timedelta(days=1), time.min)
        return start, end.replace(tzinfo=zone)

    def before(self) -> "Range":
        """The same number of days just before this range."""
        until = self.since - timedelta(days=1)
        return Range(
            since=until - timedelta(days=self.days - 1),
            until=until,
            today=self.today,
            earliest=self.earliest,
            zone=self.zone,
        )


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def read_range(
    *,
    period: str,
    since: str,
    until: str,
    now: datetime,
    setup: CrmSetup | None,
    zone: tzinfo | None = None,
) -> Range:
    today = localtime(now, zone).date()
    began = setup.leads_since or setup.enabled_at if setup is not None else None
    earliest = min(localtime(began, zone).date(), today) if began else today
    first, last = _day(since), _day(until)
    if first is None or last is None:
        days = PERIODS.get(period, DEFAULT_DAYS)
        first, last = today - timedelta(days=days - 1), today
    last = min(last, today)
    first = min(first, last)
    first = max(first, last - timedelta(days=MAX_DAYS - 1))
    return Range(since=first, until=last, today=today, earliest=earliest, zone=zone)


def _from_first_card(db: Session, *, viewer: Viewer, span: Range) -> Range:
    """The range with its first counted day moved back to the oldest lead the
    board holds.

    A board is switched on from a day, and still holds older leads: ones
    added by hand from the leads tab, or taken in before the day was moved.
    They are counted as leads, so the spend of their days must be counted
    too - or a range shows leads against no spend at all.
    """
    if viewer.scope is None:
        return span
    first = db.scalar(
        select(func.min(Lead.submitted_at))
        .join(CrmCard, CrmCard.lead_id == Lead.id)
        .where(holds(viewer.scope, CrmCard), Lead.provider != MANUAL_PROVIDER)
    )
    if first is None:
        return span
    day = localtime(first, span.zone).date()
    return replace(span, earliest=day) if day < span.earliest else span


# One group's counts. The name the older callers know it by.
Tally = SalesFigures


@dataclass(frozen=True, slots=True)
class Stats:
    state: str
    range: Range
    currency: str
    totals: Tally
    open: int
    late: int
    leads_delta_pct: float | None
    revenue_delta_pct: float | None
    funnel: list[tuple[CrmStage, int]]
    days: list[date]
    daily_leads: list[int]
    daily_won: list[int]
    managers: list[tuple[User, Tally, int]]
    ads: list[tuple[str, Tally]]
    reasons: list[tuple[str, int]]
    # Each day's own figures, in the order of ``days``.
    daily: list[Tally]
    # By the campaign that brought the lead, the most leads first.
    campaigns: list[tuple[str, Tally]]
    # The whole period one range earlier, for what changed.
    earlier: Tally | None
    # The customers typed in by hand, apart: no advert's spend is theirs.
    direct: Tally
    # Advert leads and hand-typed customers together: the board's work.
    everything: Tally
    completeness: Completeness
    # Whose figures these are, for a screen that shows more than one pair's.
    pair: dict[str, str] | None = None


def share(part: int, whole: int) -> float:
    """A part of a whole in percent, one decimal; 0 of nothing."""
    return round(part / whole * 100, 1) if whole else 0.0


def _delta(now: int, before: int) -> float | None:
    return round((now - before) / before * 100, 1) if before else None


def _cohort(viewer: Viewer, span: Range) -> Any:
    start, end = span.bounds()
    return (
        select(
            CrmCard.stage_id,
            CrmCard.assignee_id,
            CrmCard.taken_at,
            CrmCard.qualified_at,
            CrmCard.won_amount_minor,
            CrmCard.currency,
            CrmCard.closed_at,
            CrmCard.lost_reason_name,
            Lead.submitted_at,
            Lead.ad_external_id,
            Lead.campaign_external_id,
            Lead.provider,
        )
        .join(Lead, Lead.id == CrmCard.lead_id)
        .where(
            holds(viewer.scope, CrmCard),
            Lead.submitted_at >= start,
            Lead.submitted_at < end,
        )
    )


def _state(setup: CrmSetup | None) -> str:
    if setup is None or setup.state == SetupState.DRAFT:
        return "draft"
    return "on" if setup.state == SetupState.ON else "off"


@dataclass(slots=True)
class _Groups:
    """One cohort counted every way a screen cuts it."""

    # The leads adverts brought: what the spend is set against.
    total: Tally
    # The customers typed onto the board by hand: sales with no spend
    # behind them, kept out of ROAS and the price of a customer.
    direct: Tally
    # Both together: the board's own work, whoever brought the customer.
    everything: Tally
    # Each day's leads and sales, of both kinds.
    day_leads: dict[date, int]
    day_won: dict[date, int]
    by_manager: dict[uuid.UUID, Tally]
    by_ad: dict[str, Tally]
    by_campaign: dict[str, Tally]
    by_day: dict[date, Tally]
    by_stage: dict[uuid.UUID, int]
    reasons: dict[str, int]


def _minutes(since: datetime, until: datetime | None) -> float | None:
    if until is None or until < since:
        return None
    return (until - since).total_seconds() / 60


def _empty(span: Range) -> _Groups:
    days = [span.since + timedelta(days=n) for n in range(span.days)]
    return _Groups(
        total=Tally(),
        direct=Tally(spend_minor=None),
        everything=Tally(spend_minor=None),
        day_leads=dict.fromkeys(days, 0),
        day_won=dict.fromkeys(days, 0),
        by_manager={},
        by_ad={},
        by_campaign={},
        by_day={day: Tally() for day in days},
        by_stage={},
        reasons={},
    )


def _count_cohort(
    db: Session,
    *,
    viewer: Viewer,
    span: Range,
    kinds: dict[uuid.UUID, str],
    pricer: Pricer,
) -> _Groups:
    groups = _empty(span)
    for (
        stage_id,
        holder,
        taken,
        qualified,
        sum_minor,
        paid_in,
        closed,
        reason,
        came,
        ad,
        campaign,
        provider,
    ) in db.execute(_cohort(viewer, span)):
        kind = kinds.get(stage_id)
        won = kind == StageKind.WON
        # A sale reads in the pair's currency at the rate of its closing day.
        sale = (
            pricer.read(amount_minor=sum_minor or 0, currency=paid_in, at=closed)
            if won
            else 0
        )
        day = localtime(came, span.zone).date()
        if provider == MANUAL_PROVIDER:
            tallies = [groups.direct, groups.everything]
        else:
            tallies = [
                groups.total,
                groups.everything,
                groups.by_ad.setdefault(ad or "", Tally()),
                groups.by_campaign.setdefault(campaign or "", Tally()),
            ]
            if day in groups.by_day:
                tallies.append(groups.by_day[day])
        if day in groups.day_leads:
            groups.day_leads[day] += 1
            groups.day_won[day] += won
        if holder is not None:
            # A manager is not an advert: no spend is his.
            tallies.append(
                groups.by_manager.setdefault(holder, Tally(spend_minor=None))
            )
        wait = _minutes(came, taken)
        deal = _minutes(came, closed) if won else None
        for tally in tallies:
            tally.leads += 1
            tally.taken += taken is not None
            tally.judged += kind != StageKind.NEW
            # Qualified as everywhere else (``crm.quality``): sold, or moved
            # into a quality column and still open. Refused later is not.
            tally.qualified += won or (qualified is not None and kind == StageKind.OPEN)
            tally.won += won
            tally.lost += kind == StageKind.LOST
            tally.junk += kind == StageKind.JUNK
            if sale is None:
                tally.unpriced += 1
            else:
                tally.revenue_minor += sale
            if wait is not None:
                tally.waits.append(wait)
            if deal is not None:
                tally.deals.append(deal)
        groups.by_stage[stage_id] = groups.by_stage.get(stage_id, 0) + 1
        if kind == StageKind.LOST:
            groups.reasons[reason or "—"] = groups.reasons.get(reason or "—", 0) + 1
    return groups


def spend_rows(
    db: Session, *, scope: Scope, setup: CrmSetup | None, since: date, until: date
) -> list[tuple[str, str, date, int, str]]:
    """The spend this CRM's leads are set against: (advert, campaign, day,
    minor units, currency), in the ad account's own currency.

    Whose spend it is follows whose leads the CRM takes. A campaign feeds
    the CRM if a lead of it ever became a card here, or it was built here
    with a lead form for this pair's page; inside those campaigns an advert counts
    by the rule a new lead of it would be taken by
    (``services.takes_lead``): every advert, or the ticked ones, or - with
    «yangi reklamalar ham» - the ones that were not there to tick. An
    advert that brought a card always counts, ticked now or not. So an
    advert that spent and brought nobody is still in the sum, and a
    campaign for messages or reach, whose results never reach the CRM, is
    not.
    """
    from app.modules.ads.models import Ad, AdSet, Campaign
    from app.modules.ads.selectors.owned import campaigns_by_pair
    from app.modules.integrations.models import PageAccount
    from app.modules.integrations.selectors import Pair
    from app.modules.metrics.constants import MetricLevel
    from app.modules.metrics.models import MetricsDaily as M

    carded = (
        select(Lead.ad_external_id, Lead.campaign_external_id)
        .join(CrmCard, CrmCard.lead_id == Lead.id)
        .where(scope.holds(CrmCard))
        .distinct()
    )
    ads_with_cards: set[str] = set()
    feeding: set[str] = set()
    for ad, campaign in db.execute(carded):
        if ad:
            ads_with_cards.add(ad)
        if campaign:
            feeding.add(campaign)
    account = db.get(AdAccount, scope.ad_account_id)
    page = db.get(PageAccount, scope.page_id)
    if account is None or page is None:
        return []
    pair = Pair(page=page, account=account, stored=True, first=True)
    owner = db.get(User, scope.owner_id)
    if owner is None:
        return []
    own = campaigns_by_pair(db, owner=owner, pairs=[pair]).get(pair.key)
    # Only the campaigns built for this page. One built with no page named
    # belongs to the account's every pair; it counts here once a lead of it
    # is a card here, and not before - or two pairs would both carry it.
    built = sorted(own.exact) if own else []
    if built:
        feeding.update(
            db.scalars(
                select(Campaign.external_id)
                .join(AdSet, AdSet.campaign_id == Campaign.id)
                .join(Ad, Ad.adset_id == AdSet.id)
                .where(
                    Campaign.owner_id == scope.owner_id,
                    Campaign.external_id.in_(built),
                    Ad.lead_form_external_id != "",
                )
                .distinct()
            )
        )
    if not feeding and not ads_with_cards:
        return []
    rows = db.execute(
        select(
            M.external_id,
            M.campaign_external_id,
            M.date,
            func.sum(M.spend_minor),
            func.max(M.currency),
        )
        .where(
            M.owner_id == scope.owner_id,
            M.ad_account_id == scope.ad_account_id,
            M.level == str(MetricLevel.AD),
            M.date >= since,
            M.date <= until,
            M.spend_minor > 0,
            or_(
                M.campaign_external_id.in_(feeding),
                M.external_id.in_(ads_with_cards),
            ),
        )
        .group_by(M.external_id, M.campaign_external_id, M.date)
    )
    by_ad = list(rows)
    every = setup is None or setup.every_ad
    ticked = set(setup.ad_external_ids or []) if setup is not None else set()
    offered = set(setup.offered_ad_ids or []) if setup is not None else set()
    new_too = setup is not None and setup.take_new_ads

    def counts(ad: str) -> bool:
        if every or ad in ticked or ad in ads_with_cards:
            return True
        return new_too and ad not in offered

    found = [
        (ad, campaign, day, int(minor), currency or account.currency)
        for ad, campaign, day, minor, currency in by_ad
        if counts(ad)
    ]
    if every and feeding:
        found.extend(
            _unread_by_ad(
                db,
                scope=scope,
                feeding=feeding,
                since=since,
                until=until,
                read=found,
                currency=account.currency,
            )
        )
    return found


def _unread_by_ad(
    db: Session,
    *,
    scope: Scope,
    feeding: set[str],
    since: date,
    until: date,
    read: list[tuple[str, str, date, int, str]],
    currency: str,
) -> list[tuple[str, str, date, int, str]]:
    """What a campaign's ad sets spent on a day beyond what its adverts' rows
    hold, as a row with no advert.

    The dashboards sum the ad sets' rows, and an advert's rows are read
    apart and can lag or be missing. Where every advert of a campaign
    counts, the campaign's spend is its ad sets' - so the remainder is the
    CRM's too, only no one advert's. With ticked adverts the remainder
    cannot be given to the ticked or the unticked, and is left out.
    """
    from app.modules.metrics.constants import MetricLevel
    from app.modules.metrics.models import MetricsDaily as M

    held: dict[tuple[str, date], int] = {}
    for _, campaign, day, minor, _ in read:
        held[(campaign, day)] = held.get((campaign, day), 0) + minor
    rows = db.execute(
        select(
            M.campaign_external_id,
            M.date,
            func.sum(M.spend_minor),
            func.max(M.currency),
        )
        .where(
            M.owner_id == scope.owner_id,
            M.ad_account_id == scope.ad_account_id,
            M.level == str(MetricLevel.ADSET),
            M.date >= since,
            M.date <= until,
            M.spend_minor > 0,
            M.campaign_external_id.in_(feeding),
        )
        .group_by(M.campaign_external_id, M.date)
    )
    return [
        ("", campaign, day, int(minor) - held.get((campaign, day), 0), paid or currency)
        for campaign, day, minor, paid in rows
        if int(minor) > held.get((campaign, day), 0)
    ]


def _add_spend(
    groups: _Groups,
    rows: list[tuple[str, str, date, int, str]],
    *,
    pricer: Pricer,
) -> None:
    """Each day's spend, read in the CRM's currency at that day's rate. A
    cell that loses a day to a missing rate is marked: its sum has a hole."""
    unpriced: set[date] = set()
    for ad, campaign, day, minor, currency in rows:
        cells = [groups.total, groups.by_campaign.setdefault(campaign, Tally())]
        # A campaign's spend no advert's rows hold is nobody's line.
        if ad:
            cells.append(groups.by_ad.setdefault(ad, Tally()))
        on_day = groups.by_day.get(day)
        if on_day is not None:
            cells.append(on_day)
        value = pricer.read(amount_minor=minor, currency=currency, at=day)
        if value is None:
            unpriced.add(day)
            for tally in cells:
                tally.spend_gap = "no_rate"
            if on_day is not None:
                on_day.spend_unpriced_days = 1
            continue
        for tally in cells:
            tally.spend_minor = (tally.spend_minor or 0) + value
    groups.total.spend_unpriced_days = len(unpriced)


def _every_cell(groups: _Groups) -> list[Tally]:
    return [
        groups.total,
        groups.direct,
        groups.everything,
        *groups.by_manager.values(),
        *groups.by_ad.values(),
        *groups.by_campaign.values(),
        *groups.by_day.values(),
    ]


def _counted(
    db: Session,
    *,
    viewer: Viewer,
    setup: CrmSetup | None,
    span: Range,
    kinds: dict[uuid.UUID, str],
    pricer: Pricer,
) -> _Groups:
    from app.modules.metrics.services import ad_retention_floor

    if setup is None or setup.state == SetupState.DRAFT:
        # Never switched on: no card exists, and nothing is read to say so.
        groups = _empty(span)
        for tally in _every_cell(groups):
            tally.crm = False
        return groups
    groups = _count_cohort(db, viewer=viewer, span=span, kinds=kinds, pricer=pricer)
    # The board holds leads only from its first one's day (``_from_first_card``);
    # spend from before that day brought no card and is set against nothing.
    since = max(span.since, span.earliest)
    if viewer.scope is not None and since <= span.until:
        _add_spend(
            groups,
            spend_rows(
                db, scope=viewer.scope, setup=setup, since=since, until=span.until
            ),
            pricer=pricer,
        )
    cells = _every_cell(groups)
    # Spend per advert is kept for half a year: a range reaching further
    # back has its leads and only part of its spend.
    if since < ad_retention_floor(today=span.today):
        for tally in cells:
            if tally.spend_minor is not None:
                tally.spend_gap = "not_kept"
    crm = setup is not None and setup.state == SetupState.ON
    for tally in cells:
        tally.crm = crm
    return groups


def _most_leads(found: dict[str, Tally], shown: int) -> list[tuple[str, Tally]]:
    return sorted(
        ((key, tally) for key, tally in found.items() if key),
        key=lambda row: (-row[1].leads, -(row[1].spend_minor or 0), row[0]),
    )[:shown]


def stats(
    db: Session,
    *,
    viewer: Viewer,
    period: str = "",
    since: str = "",
    until: str = "",
    now: datetime,
) -> Stats:
    setup = setup_of(db, scope=viewer.scope)
    zone = viewer.pair.account.tzinfo() if viewer.pair is not None else None
    span = _from_first_card(
        db,
        viewer=viewer,
        span=read_range(
            period=period, since=since, until=until, now=now, setup=setup, zone=zone
        ),
    )
    stages = stages_of(db, scope=viewer.scope)
    kinds = {stage.id: stage.kind for stage in stages}
    currency = setup.currency if setup is not None else ""
    pricer = Pricer(db, target=currency)
    groups = _counted(
        db, viewer=viewer, setup=setup, span=span, kinds=kinds, pricer=pricer
    )
    total = groups.total
    days = sorted(groups.by_day)
    before = (
        _counted(
            db,
            viewer=viewer,
            setup=setup,
            span=span.before(),
            kinds=kinds,
            pricer=pricer,
        )
        if span.days > 1
        else None
    )
    earlier = before.total if before is not None else None
    everything = groups.everything

    still_open = (
        select(CrmCard.assignee_id, func.count(CrmCard.id))
        .where(holds(viewer.scope, CrmCard), CrmCard.closed_at.is_(None))
        .group_by(CrmCard.assignee_id)
    )
    open_now = sum(n for _, n in db.execute(still_open))
    late_by = dict(db.execute(still_open.where(CrmCard.due_at < now)).all())

    people = {
        user.id: user
        for user in db.scalars(select(User).where(User.id.in_(groups.by_manager)))
    }
    managers = sorted(
        (
            (people[key], tally, int(late_by.get(key, 0)))
            for key, tally in groups.by_manager.items()
            if key in people
        ),
        key=lambda row: (-row[1].won, -row[1].leads),
    )
    return Stats(
        state=_state(setup),
        range=span,
        currency=currency,
        totals=total,
        open=open_now,
        late=sum(int(n) for n in late_by.values()),
        leads_delta_pct=(
            _delta(everything.leads, before.everything.leads) if before else None
        ),
        revenue_delta_pct=(
            _delta(everything.revenue_minor, before.everything.revenue_minor)
            if before
            else None
        ),
        funnel=_funnel(stages, groups.by_stage, everything),
        days=days,
        daily_leads=[groups.day_leads[day] for day in days],
        daily_won=[groups.day_won[day] for day in days],
        managers=managers,
        ads=_most_leads(groups.by_ad, ADS_SHOWN),
        reasons=sorted(groups.reasons.items(), key=lambda row: (-row[1], row[0]))[
            :REASONS_SHOWN
        ],
        daily=[groups.by_day[day] for day in days],
        campaigns=_most_leads(groups.by_campaign, CAMPAIGNS_SHOWN),
        earlier=earlier,
        direct=groups.direct,
        everything=everything,
        completeness=completeness(total),
        pair=(
            {
                "key": viewer.pair.key,
                "page": viewer.pair.page.name or viewer.pair.page.external_id,
                "account": viewer.pair.account.name or viewer.pair.account.external_id,
            }
            if viewer.pair is not None
            else None
        ),
    )


def _funnel(
    stages: list[CrmStage], by_stage: dict[uuid.UUID, int], total: Tally
) -> list[tuple[CrmStage, int]]:
    """How many of the period's cards got as far as each column.

    The board keeps where a card is, not where it has been, so a working
    column counts the cards standing in it or in a later working column,
    and the sold ones: all of them passed through. A refused card is
    counted in its own column only - where it was dropped is not kept.
    """
    working = [s for s in stages if s.kind not in (StageKind.NEW, *_CLOSED)]
    further = total.won
    reached: dict[uuid.UUID, int] = {}
    for stage in reversed(working):
        further += by_stage.get(stage.id, 0)
        reached[stage.id] = further
    rows = []
    for stage in stages:
        if stage.kind == StageKind.NEW:
            count = total.leads
        elif stage.kind in _CLOSED:
            count = by_stage.get(stage.id, 0)
        else:
            count = reached[stage.id]
        rows.append((stage, count))
    return rows


_CLOSED: Final = (StageKind.WON, StageKind.LOST, StageKind.JUNK)
