"""How much the CRM told Meta about the leads of a range."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.crm.constants import SetupState
from app.modules.crm.models import CrmCard, CrmSetup
from app.modules.crm.quality import judged_card, junk_card, qualified_card
from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
from app.modules.leads.constants import SignalStatus
from app.modules.leads.models import Lead, LeadSignal
from app.modules.leads.selectors.reads import pixel_state
from app.modules.metrics.constants import CRM_USE_MIN_PCT, LEAD_QUALITY_MIN_PCT
from app.modules.metrics.selectors.scope import PageCampaigns
from core.metrics import formulas
from core.metrics.arithmetic import tenths

Problem = Literal["none", "no_pixel", "pixel_unselected", "connection"]
# How much signal there is: none without the CRM or a pixel, too little when
# the CRM is barely used or quality leads are rare.
Level = Literal["off", "no_pixel", "unused", "low", "ok"]


@dataclass(frozen=True, slots=True)
class LeadQuality:
    crm: bool
    leads: int
    marked: int
    qualified: int
    unqualified: int
    sent: int
    waiting: int
    failed: int
    expired: int
    last_sent_at: datetime | None
    problem: Problem
    marked_pct: float = 0.0
    qualified_pct: float = 0.0
    unqualified_pct: float = 0.0
    level: Level = "off"
    # The share ``low`` is under, for the sentence that says so.
    quality_floor_pct: int = LEAD_QUALITY_MIN_PCT


def _pct(part: int, leads: int) -> float:
    return float(tenths(formulas.lead_share(part, leads)) or 0)


def level_of(
    *, crm: bool, problem: Problem, marked_pct: float, qualified_pct: float
) -> Level:
    if not crm:
        return "off"
    if problem != "none":
        return "no_pixel"
    if marked_pct < CRM_USE_MIN_PCT:
        return "unused"
    if qualified_pct < LEAD_QUALITY_MIN_PCT:
        return "low"
    return "ok"


def lead_quality(
    db: Session, *, owner: User, page: PageCampaigns, since: date, until: date
) -> LeadQuality | None:
    """``None`` when the range holds no lead a CRM could speak of."""
    home = page.home
    if home is None or not page.ids:
        return None
    zone = home.tzinfo()
    start = datetime.combine(since, time.min).replace(tzinfo=zone)
    end = datetime.combine(until + timedelta(days=1), time.min).replace(tzinfo=zone)
    in_range = (
        Lead.owner_id == owner.id,
        Lead.is_test.is_(False),
        Lead.is_organic.is_(False),
        Lead.campaign_external_id.in_(list(page.ids)),
        Lead.submitted_at >= start,
        Lead.submitted_at < end,
    )
    leads = int(db.scalar(select(func.count(Lead.id)).where(*in_range)) or 0)
    if not leads:
        return None
    marked, qualified, unqualified = db.execute(
        select(
            func.count(CrmCard.id).filter(judged_card()),
            func.count(CrmCard.id).filter(qualified_card()),
            func.count(CrmCard.id).filter(junk_card()),
        )
        .join(Lead, Lead.id == CrmCard.lead_id)
        .where(*in_range)
    ).one()
    told = dict(
        db.execute(
            select(LeadSignal.status, func.count(LeadSignal.id))
            .join(Lead, Lead.id == LeadSignal.lead_id)
            .where(*in_range, LeadSignal.stage != "received")
            .group_by(LeadSignal.status)
        ).all()
    )
    last_sent_at = db.scalar(
        select(func.max(LeadSignal.sent_at))
        .join(Lead, Lead.id == LeadSignal.lead_id)
        .where(*in_range)
    )
    running = db.scalar(
        select(CrmSetup.id)
        .where(
            CrmSetup.owner_id == owner.id,
            CrmSetup.ad_account_id.in_([account.id for account in page.accounts]),
            CrmSetup.state == SetupState.ON,
        )
        .limit(1)
    )
    crm = running is not None
    problem = _problem(db, owner=owner, page=page)
    marked_pct = _pct(marked, leads)
    qualified_pct = _pct(qualified, leads)
    return LeadQuality(
        crm=crm,
        leads=leads,
        marked=marked,
        qualified=qualified,
        unqualified=unqualified,
        sent=told.get(SignalStatus.SENT, 0),
        waiting=told.get(SignalStatus.PENDING, 0),
        failed=told.get(SignalStatus.FAILED, 0),
        expired=told.get(SignalStatus.EXPIRED, 0),
        last_sent_at=last_sent_at,
        problem=problem,
        marked_pct=marked_pct,
        qualified_pct=qualified_pct,
        unqualified_pct=_pct(unqualified, leads),
        level=level_of(
            crm=crm,
            problem=problem,
            marked_pct=marked_pct,
            qualified_pct=qualified_pct,
        ),
    )


def _problem(db: Session, *, owner: User, page: PageCampaigns) -> Problem:
    home = page.home
    if home is None:
        return "no_pixel"
    state = pixel_state(db, owner=owner, ad_account=home)
    if state != "ready":
        return "pixel_unselected" if state == "unselected" else "no_pixel"
    if home.connection.status not in USABLE_CONNECTION_STATUSES:
        return "connection"
    return "none"


__all__ = ["LeadQuality", "lead_quality", "level_of"]
