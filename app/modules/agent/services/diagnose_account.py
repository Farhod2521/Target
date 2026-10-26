"""A cause for every delivering group, written down once a night."""

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import and_, delete, not_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.agent.models import AdSetDiagnosis
from app.modules.agent.selectors.facts import account_facts
from app.modules.agent.selectors.pair_views import pair_views
from app.modules.agent.selectors.policy import policy_for
from app.modules.agent.selectors.window import yesterday
from app.modules.integrations.models import AdAccount
from core.agent import Policy
from core.agent.diagnosis import Diagnosis, diagnose

REFRESHED = (
    "name",
    "cause",
    "signals",
    "evidence",
    "since",
    "until",
    "diagnosed_at",
    "updated_at",
)


def diagnose_account(db: Session, *, owner_id: str, now: datetime) -> int:
    """Diagnose every group on every ad account in this owner's subscription."""
    from app.modules.billing.selectors.subscription import has_live_subscription
    from app.modules.integrations.selectors.slots import enabled_ad_accounts

    owner = db.get(User, uuid.UUID(str(owner_id)))
    if owner is None:
        return 0
    accounts = enabled_ad_accounts(db, owner=owner)
    if not accounts or not has_live_subscription(db, owner=owner):
        db.execute(delete(AdSetDiagnosis).where(AdSetDiagnosis.owner_id == owner.id))
        db.commit()
        return 0
    row = policy_for(db, owner=owner)
    policy = row.as_policy() if row is not None else Policy()
    found = _diagnosed(db, owner=owner, accounts=accounts, policy=policy, now=now)
    until = yesterday(tzinfo=accounts[0].tzinfo(), now=now)
    _keep(
        db,
        owner=owner,
        provider=accounts[0].provider,
        found=tuple(found),
        window=(until - timedelta(days=policy.window_days - 1), until),
        now=now,
    )
    return len(found)


def _diagnosed(
    db: Session,
    *,
    owner: User,
    accounts: list[AdAccount],
    policy: Policy,
    now: datetime,
) -> list[Diagnosis]:
    """Tonight's causes, pair by pair, one per group."""
    from app.modules.ads.selectors.pages import page_scope

    whole = page_scope(db, owner=owner)
    views = pair_views(db, owner=owner, whole=whole, accounts=accounts)
    reads = (
        [(view.scope, account) for view in views for account in view.accounts]
        if views
        else [(whole, account) for account in accounts]
    )
    found: dict[str, Diagnosis] = {}
    for scope, account in reads:
        facts = account_facts(
            db, owner=owner, account=account, policy=policy, now=now, scope=scope
        )
        for item in diagnose(account=facts, policy=policy):
            found.setdefault(item.adset_id, item)
    return list(found.values())


def _keep(
    db: Session,
    *,
    owner: User,
    provider: str,
    found: tuple[Diagnosis, ...],
    window: tuple[date, date],
    now: datetime,
) -> None:
    """Write tonight's causes over this owner's rows, and drop the rest. Commits."""
    since, until = window
    if found:
        rows = [
            {
                "id": uuid.uuid4(),
                "created_at": now,
                "updated_at": now,
                "owner_id": owner.id,
                "provider": provider,
                "adset_external_id": item.adset_id,
                "name": item.name,
                "cause": item.cause,
                "signals": list(item.signals),
                "evidence": dict(item.evidence),
                "since": since,
                "until": until,
                "diagnosed_at": now,
            }
            for item in found
        ]
        statement = insert(AdSetDiagnosis).values(rows)
        db.execute(
            statement.on_conflict_do_update(
                constraint="uniq_diagnosis_per_adset",
                set_={name: statement.excluded[name] for name in REFRESHED},
            )
        )
    db.execute(
        delete(AdSetDiagnosis).where(
            AdSetDiagnosis.owner_id == owner.id,
            not_(
                and_(
                    AdSetDiagnosis.provider == provider,
                    AdSetDiagnosis.adset_external_id.in_(
                        [item.adset_id for item in found]
                    ),
                )
            ),
        )
    )
    db.commit()


__all__ = ["diagnose_account"]
