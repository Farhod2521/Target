"""What is wrong across every account, said the way a customer feels it.

Urgent is money or a lead being lost right now that will not stop by itself;
everything else waits. The cause belongs to the engineer's console.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.modules.accounts.models import User
from app.modules.ads.constants import LaunchStatus
from app.modules.ads.models import CampaignLaunch
from app.modules.backoffice.constants import EXPIRING_DAYS, STUCK_HOLD_HOURS, Severity
from app.modules.backoffice.selectors.days import days_left
from app.modules.billing.constants import LIVE_SUBSCRIPTION_STATUSES
from app.modules.billing.models import Subscription
from app.modules.billing.selectors import expiring_subscriptions, held_transactions
from app.modules.integrations.models import AdAccount
from app.modules.integrations.selectors import broken_meta_connections
from app.modules.leads.constants import SWEEP_STUCK_DAYS
from app.modules.leads.selectors import orphan_pages, stuck_sweep_owners
from app.modules.metrics.selectors import GAP_DAYS, lead_gaps_everywhere

ORPHAN_WINDOW_DAYS = 30
FEED_ROWS = 20
SHORT_LABELS = {
    "connection": "Facebook uzilgan",
    "account_blocked": "Reklama akkaunti bloklangan",
    "payment_due": "Meta'da qarz",
    "lead_gap": "Murojaatlar yetmayapti",
    "sweep": "Murojaatlar tekshirilmayapti",
    "launch": "Reklama yaratilmadi",
    "orphan": "Egasiz murojaatlar",
    "hold": "To'lov tugamagan",
    "expiring": "Obuna tugayapti",
    "setup": "Sozlash tugamagan",
}


@dataclass(frozen=True, slots=True)
class Problem:
    """One thing wrong, and the one thing to do about it."""

    kind: str
    severity: str
    owner_id: UUID | None
    who: str
    what: str
    since: datetime | None
    action: str

    @property
    def label(self) -> str:
        return SHORT_LABELS.get(self.kind, self.what)

    @property
    def urgent(self) -> bool:
        return self.severity == str(Severity.URGENT)


def _connections(db: Session, *, limit: int | None) -> list[Problem]:
    return [
        Problem(
            kind="connection",
            severity=Severity.URGENT,
            owner_id=link.owner_id,
            who=link.owner.email,
            what="Facebook ulanishi uzilgan — reklama va lidlar to'xtagan",
            since=link.updated_at,
            action="Mijozga xabar",
        )
        for link in broken_meta_connections(db)[:limit]
    ]


def _ad_accounts(db: Session, *, limit: int | None) -> list[Problem]:
    """A chosen ad account Meta stopped: for a debt, or blocked outright.

    Only the account the cabinet runs on; one picked once and left is not
    costing anybody anything.
    """
    query = (
        select(AdAccount)
        .options(joinedload(AdAccount.owner))
        .join(User, User.id == AdAccount.owner_id)
        .where(
            AdAccount.is_active.is_(True),
            User.is_staff.is_(False),
            (AdAccount.payment_due.is_(True)) | (AdAccount.may_advertise.is_(False)),
        )
        .order_by(AdAccount.synced_at.asc().nulls_last(), AdAccount.updated_at)
    )
    if limit:
        query = query.limit(limit)
    found = []
    for account in db.scalars(query):
        owes = bool(account.payment_due)
        found.append(
            Problem(
                kind="payment_due" if owes else "account_blocked",
                severity=Severity.URGENT,
                owner_id=account.owner_id,
                who=account.owner.email,
                what=(
                    "Meta'da to'lanmagan qarz — reklama to'xtagan"
                    if owes
                    else "Meta reklama akkauntini bloklagan — reklama yurmaydi"
                ),
                since=account.synced_at or account.updated_at,
                action="Mijozga xabar",
            )
        )
    return found


def _orphans(db: Session, *, now: datetime) -> list[Problem]:
    since = now - timedelta(days=ORPHAN_WINDOW_DAYS)
    return [
        Problem(
            kind="orphan",
            severity=Severity.WAITING,
            owner_id=None,
            who=f"Sahifa {page.page_external_id}",
            what=f"{page.deliveries} ta lid hech kimga bog'lanmadi",
            since=page.last_seen,
            action="Biriktirish",
        )
        for page in orphan_pages(db, since=since)
    ]


def _launches(db: Session, *, limit: int | None) -> list[Problem]:
    query = (
        select(CampaignLaunch)
        .options(joinedload(CampaignLaunch.owner))
        .where(CampaignLaunch.status == LaunchStatus.FAILED)
        .order_by(CampaignLaunch.updated_at.desc())
    )
    if limit:
        query = query.limit(limit)
    return [
        Problem(
            kind="launch",
            severity=Severity.URGENT,
            owner_id=launch.owner_id,
            who=launch.owner.email,
            what="Reklama yaratilmadi — mijoz oxirigacha yeta olmadi",
            since=launch.finished_at or launch.updated_at,
            action="Ko'rish",
        )
        for launch in db.scalars(query)
    ]


def _holds(db: Session, *, now: datetime, limit: int | None) -> list[Problem]:
    cutoff = now - timedelta(hours=STUCK_HOLD_HOURS)
    return [
        Problem(
            kind="hold",
            severity=Severity.WAITING,
            owner_id=attempt.owner_id,
            who=attempt.owner.email if attempt.owner else "",
            what="To'lov tugamagan — yangi hisob chiqarib bo'lmaydi",
            since=attempt.created_at,
            action="Ko'rish",
        )
        for attempt in held_transactions(db, cutoff=cutoff)[:limit]
    ]


def _expiring(db: Session, *, now: datetime, limit: int | None) -> list[Problem]:
    rows = expiring_subscriptions(
        db, start=now, end=now + timedelta(days=EXPIRING_DAYS)
    )[:limit]
    return [
        Problem(
            kind="expiring",
            severity=Severity.WAITING,
            owner_id=row.owner_id,
            who=row.owner.email,
            what=_ending(days_left(expires_at=row.expires_at, now=now)),
            since=None,
            action="Qo'ng'iroq",
        )
        for row in rows
    ]


def _ending(days: int) -> str:
    if days == 0:
        return "Obuna bugun tugaydi"
    return f"Obuna {days} kundan keyin tugaydi"


def _unfinished_setup(
    db: Session, *, now: datetime, limit: int | None
) -> list[Problem]:
    """Entitled and not yet prepared: somebody paying who cannot advertise."""
    query = (
        select(Subscription)
        .options(joinedload(Subscription.owner))
        .where(
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            Subscription.expires_at > now,
            Subscription.setup_completed_at.is_(None),
        )
        .order_by(Subscription.started_at)
    )
    if limit:
        query = query.limit(limit)
    return [
        Problem(
            kind="setup",
            severity=Severity.WAITING,
            owner_id=row.owner_id,
            who=row.owner.email,
            what="Sozlash yakunlanmagan — hali reklama bera olmaydi",
            since=row.started_at,
            action="Qo'ng'iroq",
        )
        for row in db.scalars(query)
    ]


def _lead_gaps(db: Session, *, now: datetime, limit: int | None) -> list[Problem]:
    return [
        Problem(
            kind="lead_gap",
            severity=Severity.URGENT,
            owner_id=row.owner_id,
            who=row.email,
            what=(
                f"{GAP_DAYS} kunda Meta {row.reported} ta murojaat sanadi, "
                f"bazaga {row.ours} tasi yetdi"
            ),
            since=None,
            action="Ko'rish",
        )
        for row in lead_gaps_everywhere(db, now=now, limit=limit)
    ]


def _stuck_sweeps(db: Session, *, now: datetime, limit: int | None) -> list[Problem]:
    return [
        Problem(
            kind="sweep",
            severity=Severity.WAITING,
            owner_id=row.owner_id,
            who=row.email,
            what=(
                f"{row.forms} ta formadagi murojaatlar {SWEEP_STUCK_DAYS} kundan "
                "beri qayta tekshirilmadi"
            ),
            since=None,
            action="Ko'rish",
        )
        for row in stuck_sweep_owners(db, now=now, limit=limit)
    ]


def problems(
    db: Session, *, now: datetime, limit: int | None = FEED_ROWS
) -> list[Problem]:
    """Everything wrong, urgent first and the oldest first inside each band.

    ``limit`` caps each check; ``None`` reads every row, as a filter needs.
    """
    found = (
        _connections(db, limit=limit)
        + _ad_accounts(db, limit=limit)
        + _lead_gaps(db, now=now, limit=limit)
        + _stuck_sweeps(db, now=now, limit=limit)
        + _launches(db, limit=limit)
        + _orphans(db, now=now)
        + _holds(db, now=now, limit=limit)
        + _expiring(db, now=now, limit=limit)
        + _unfinished_setup(db, now=now, limit=limit)
    )
    order = {str(Severity.URGENT): 0, str(Severity.WAITING): 1}
    return sorted(found, key=lambda p: (order.get(p.severity, 9), p.since or now))


def problems_of(db: Session, *, owner_id: UUID, now: datetime) -> list[Problem]:
    """Everything wrong with one account, worst first - for its card."""
    return [p for p in problems(db, now=now, limit=None) if p.owner_id == owner_id]


def worst_by_owner(db: Session, *, now: datetime) -> dict[UUID, Problem]:
    """Each troubled account's worst problem - the one its list row names."""
    worst: dict[UUID, Problem] = {}
    for problem in problems(db, now=now, limit=None):
        if problem.owner_id is not None:
            worst.setdefault(problem.owner_id, problem)
    return worst
