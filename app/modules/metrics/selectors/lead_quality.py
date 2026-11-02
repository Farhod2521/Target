"""How much the CRM told Meta about the leads of a range."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.crm.constants import SetupState, StageKind
from app.modules.crm.models import CrmCard, CrmSetup, CrmStage
from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
from app.modules.leads.constants import SignalStatus
from app.modules.leads.models import Lead, LeadSignal
from app.modules.leads.selectors.reads import pixel_state
from app.modules.metrics.selectors.scope import PageCampaigns

Problem = Literal["none", "no_pixel", "pixel_unselected", "connection"]


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
    kinds = db.execute(
        select(CrmStage.kind, CrmCard.qualified_at.is_not(None), func.count(CrmCard.id))
        .join(CrmCard, CrmCard.stage_id == CrmStage.id)
        .join(Lead, Lead.id == CrmCard.lead_id)
        .where(*in_range)
        .group_by(CrmStage.kind, CrmCard.qualified_at.is_not(None))
    ).all()
    marked = qualified = unqualified = 0
    for kind, was_qualified, count in kinds:
        if kind != StageKind.NEW:
            marked += count
        if kind == StageKind.JUNK:
            unqualified += count
        elif kind == StageKind.WON or (kind == StageKind.OPEN and was_qualified):
            qualified += count
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
    return LeadQuality(
        crm=running is not None,
        leads=leads,
        marked=marked,
        qualified=qualified,
        unqualified=unqualified,
        sent=told.get(SignalStatus.SENT, 0),
        waiting=told.get(SignalStatus.PENDING, 0),
        failed=told.get(SignalStatus.FAILED, 0),
        expired=told.get(SignalStatus.EXPIRED, 0),
        last_sent_at=last_sent_at,
        problem=_problem(db, owner=owner, page=page),
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


__all__ = ["LeadQuality", "lead_quality"]
