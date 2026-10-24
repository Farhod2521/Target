"""Reads over one account's agent settings, and whether the night check keeps up."""

import uuid
from datetime import datetime, time, timedelta

from metaads import PROVIDER as META
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.common import timezone
from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import Ad, AdSet
from app.modules.agent.constants import CHECK_STALE_HOURS
from app.modules.agent.models import AdSetDiagnosis, AgentPolicy
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily


def policy_for(db: Session, *, owner: User) -> AgentPolicy | None:
    """This account's settings row, or nothing if it was never saved."""
    return db.scalar(select(AgentPolicy).where(AgentPolicy.owner_id == owner.id))


def is_enabled(db: Session, *, owner: User) -> bool:
    """On for every account unless its owner switched it off."""
    return (
        db.scalar(
            select(AgentPolicy.id).where(
                AgentPolicy.owner_id == owner.id, AgentPolicy.is_enabled.is_(False)
            )
        )
        is None
    )


def agent_owner_ids(db: Session, *, now: datetime) -> set[uuid.UUID]:
    """Every account the nightly agent runs for."""
    from app.modules.billing.selectors import entitled_owner_ids

    refused = select(AgentPolicy.owner_id).where(AgentPolicy.is_enabled.is_(False))
    return set(
        db.scalars(
            select(AdAccount.owner_id)
            .where(
                AdAccount.is_active.is_(True),
                AdAccount.owner_id.in_(entitled_owner_ids(now=now)),
                AdAccount.owner_id.not_in(refused),
            )
            .distinct()
        )
    )


def check_is_late(db: Session, *, owner: User, now: datetime) -> datetime | None:
    """When the last finished night was, if that is long enough ago to say so."""
    if not is_enabled(db, owner=owner):
        return None
    policy = policy_for(db, owner=owner)
    if policy is None:
        return None
    since = policy.last_run_at or policy.created_at
    return since if now - since > timedelta(hours=CHECK_STALE_HOURS) else None


def diagnoses(owner: User):  # type: ignore[no-untyped-def]
    """This owner's causes, one row per group, as a query to narrow."""
    return select(AdSetDiagnosis).where(AdSetDiagnosis.owner_id == owner.id)


def owners_to_diagnose(db: Session) -> list[str]:
    """Everybody the nightly sweep has something to do for."""
    connected = db.scalars(
        select(AdAccount.owner_id)
        .where(AdAccount.provider == META, AdAccount.is_current.is_(True))
        .distinct()
    )
    written = db.scalars(select(AdSetDiagnosis.owner_id).distinct())
    return sorted({str(owner_id) for owner_id in [*connected, *written]})


def owners_with_faults(db: Session) -> list[str]:
    """Every owner with an advert or a group stopped over a reported fault."""
    ads = db.scalars(
        select(Ad.owner_id)
        .where(
            Ad.delivery == Delivery.REJECTED,
            (func.cardinality(Ad.issue_codes) > 0)
            | (cast(Ad.review_feedback, JSONB) != cast("{}", JSONB)),
        )
        .distinct()
    )
    groups = db.scalars(
        select(AdSet.owner_id)
        .where(
            AdSet.delivery == Delivery.REJECTED,
            func.cardinality(AdSet.issue_codes) > 0,
        )
        .distinct()
    )
    return sorted({str(owner_id) for owner_id in [*ads, *groups]})


def stale_accounts(
    db: Session, *, owner: User, accounts: list[AdAccount], now: datetime
) -> list[AdAccount]:
    """The accounts whose yesterday has rows, none of them written after it ended."""
    found: list[AdAccount] = []
    for account in accounts:
        zone = account.tzinfo()
        today = timezone.localtime(now, zone).date()
        ended = datetime.combine(today, time.min, tzinfo=zone)
        latest = db.scalar(
            select(func.max(MetricsDaily.synced_at)).where(
                MetricsDaily.owner_id == owner.id,
                MetricsDaily.level == MetricLevel.ADSET,
                MetricsDaily.ad_account_id == account.id,
                MetricsDaily.date == today - timedelta(days=1),
            )
        )
        if latest is not None and latest < ended:
            found.append(account)
    return found


__all__ = [
    "agent_owner_ids",
    "check_is_late",
    "diagnoses",
    "is_enabled",
    "owners_to_diagnose",
    "owners_with_faults",
    "policy_for",
    "stale_accounts",
]
