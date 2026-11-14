"""What one pair's CRM did with the leads of a period.

Every figure is counted over one cohort: the cards whose enquiry came in
the period. A lead of the 3rd sold on the 20th is a sale of the 3rd's
leads, so leads, quality, sales and conversion always describe the same
people and conversion can never pass 100%. Only ``open`` and ``late``
are the board as it stands now.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from statistics import median
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.dates import localtime, office_zone
from app.modules.accounts.models import User
from app.modules.crm.constants import SetupState, StageKind
from app.modules.crm.models import CrmCard, CrmSetup, CrmStage
from app.modules.crm.selectors import Viewer, holds, setup_of, stages_of
from app.modules.leads.models import Lead

PERIODS: Final = {"today": 1, "7": 7, "30": 30, "90": 90}
DEFAULT_DAYS: Final = 30
# The longest typed range: a year and a day, so «last year to today» fits.
MAX_DAYS: Final = 367
ADS_SHOWN: Final = 20
REASONS_SHOWN: Final = 8


@dataclass(frozen=True, slots=True)
class Range:
    since: date
    until: date
    today: date
    earliest: date

    @property
    def days(self) -> int:
        return (self.until - self.since).days + 1

    def bounds(self) -> tuple[datetime, datetime]:
        zone = office_zone()
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
        )


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def read_range(
    *, period: str, since: str, until: str, now: datetime, setup: CrmSetup | None
) -> Range:
    today = localtime(now).date()
    began = setup.leads_since or setup.enabled_at if setup is not None else None
    earliest = min(localtime(began).date(), today) if began else today
    first, last = _day(since), _day(until)
    if first is None or last is None:
        days = PERIODS.get(period, DEFAULT_DAYS)
        first, last = today - timedelta(days=days - 1), today
    last = min(last, today)
    first = min(first, last)
    first = max(first, last - timedelta(days=MAX_DAYS - 1))
    return Range(since=first, until=last, today=today, earliest=earliest)


@dataclass(slots=True)
class Tally:
    leads: int = 0
    taken: int = 0
    qualified: int = 0
    won: int = 0
    lost: int = 0
    revenue_minor: int = 0
    waits: list[float] = field(default_factory=list)

    @property
    def conversion_pct(self) -> float:
        return share(self.won, self.leads)

    @property
    def first_response_min(self) -> int | None:
        return round(median(self.waits)) if self.waits else None


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
            CrmCard.lost_reason_name,
            Lead.submitted_at,
            Lead.ad_external_id,
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
    span = read_range(period=period, since=since, until=until, now=now, setup=setup)
    stages = stages_of(db, scope=viewer.scope)
    kinds = {stage.id: stage.kind for stage in stages}
    total = Tally()
    by_manager: dict[uuid.UUID, Tally] = {}
    by_ad: dict[str, Tally] = {}
    by_stage: dict[uuid.UUID, int] = {}
    reasons: dict[str, int] = {}
    days = [span.since + timedelta(days=n) for n in range(span.days)]
    place = {day: n for n, day in enumerate(days)}
    daily_leads, daily_won = [0] * len(days), [0] * len(days)
    for stage_id, holder, taken, qualified, sum_minor, reason, came, ad in db.execute(
        _cohort(viewer, span)
    ):
        kind = kinds.get(stage_id)
        tallies = [total, by_ad.setdefault(ad or "", Tally())]
        if holder is not None:
            tallies.append(by_manager.setdefault(holder, Tally()))
        wait = (taken - came).total_seconds() / 60 if taken and taken >= came else None
        for tally in tallies:
            tally.leads += 1
            tally.taken += taken is not None
            tally.qualified += qualified is not None
            tally.won += kind == StageKind.WON
            tally.lost += kind == StageKind.LOST
            if kind == StageKind.WON:
                tally.revenue_minor += sum_minor or 0
            if wait is not None:
                tally.waits.append(wait)
        by_stage[stage_id] = by_stage.get(stage_id, 0) + 1
        at = place.get(localtime(came).date())
        if at is not None:
            daily_leads[at] += 1
            daily_won[at] += kind == StageKind.WON
        if kind == StageKind.LOST:
            reasons[reason or "—"] = reasons.get(reason or "—", 0) + 1

    earlier = Tally()
    if span.days > 1:
        for stage_id, _, _, _, sum_minor, *_ in db.execute(
            _cohort(viewer, span.before())
        ):
            earlier.leads += 1
            if kinds.get(stage_id) == StageKind.WON:
                earlier.revenue_minor += sum_minor or 0

    still_open = (
        select(CrmCard.assignee_id, func.count(CrmCard.id))
        .where(holds(viewer.scope, CrmCard), CrmCard.closed_at.is_(None))
        .group_by(CrmCard.assignee_id)
    )
    open_now = sum(n for _, n in db.execute(still_open))
    late_by = dict(db.execute(still_open.where(CrmCard.due_at < now)).all())

    people = {
        user.id: user
        for user in db.scalars(select(User).where(User.id.in_(by_manager)))
    }
    managers = sorted(
        (
            (people[key], tally, int(late_by.get(key, 0)))
            for key, tally in by_manager.items()
            if key in people
        ),
        key=lambda row: (-row[1].won, -row[1].leads),
    )
    return Stats(
        state=_state(setup),
        range=span,
        currency=setup.currency if setup is not None else "",
        totals=total,
        open=open_now,
        late=sum(int(n) for n in late_by.values()),
        leads_delta_pct=_delta(total.leads, earlier.leads) if span.days > 1 else None,
        revenue_delta_pct=(
            _delta(total.revenue_minor, earlier.revenue_minor)
            if span.days > 1
            else None
        ),
        funnel=_funnel(stages, by_stage, total),
        days=days,
        daily_leads=daily_leads,
        daily_won=daily_won,
        managers=managers,
        ads=sorted(
            ((key, tally) for key, tally in by_ad.items() if key),
            key=lambda row: (-row[1].leads, row[0]),
        )[:ADS_SHOWN],
        reasons=sorted(reasons.items(), key=lambda row: (-row[1], row[0]))[
            :REASONS_SHOWN
        ],
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
