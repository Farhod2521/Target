"""Tonight's frequency levels: start groups again, raise them, close the rest."""

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.modules.accounts.models import User
from app.modules.agent.constants import FrequencyAnswer
from app.modules.agent.models import FrequencyAlert
from app.modules.agent.selectors.frequency import (
    Candidate,
    cost_between,
    frequency_candidates,
    newest_ads,
)
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from core.agent.frequency import RANK, decide

AFTER = timedelta(days=7)


def check_frequency(db: Session, *, owner: User, now: datetime) -> list[FrequencyAlert]:
    """Write tonight's levels. Returns the rows raised tonight. Commits."""
    candidates = {
        item.reading.adset_id: item
        for item in frequency_candidates(db, owner=owner, now=now)
    }
    open_rows: dict[str, list[FrequencyAlert]] = defaultdict(list)
    for row in db.scalars(
        select(FrequencyAlert).where(
            FrequencyAlert.owner_id == owner.id, FrequencyAlert.closed_at.is_(None)
        )
    ):
        open_rows[row.adset_external_id].append(row)
    newest = newest_ads(db, owner=owner, adset_ids=list(open_rows))
    raised: list[FrequencyAlert] = []
    for adset_id, rows in open_rows.items():
        if adset_id not in candidates:
            _close(rows, now=now)
    for adset_id, found in candidates.items():
        made = _one(
            db,
            owner=owner,
            found=found,
            rows=open_rows.get(adset_id, []),
            newest=newest.get(adset_id),
            now=now,
        )
        if made is not None:
            raised.append(made)
    db.commit()
    _price_after(db, owner=owner, now=now)
    return raised


def _one(
    db: Session,
    *,
    owner: User,
    found: Candidate,
    rows: list[FrequencyAlert],
    newest: datetime | None,
    now: datetime,
) -> FrequencyAlert | None:
    """One group: start it again, raise it a level, or leave it."""
    new_creative = bool(
        rows and newest and newest > min(row.created_at for row in rows)
    )
    decision = decide(
        reading=found.reading,
        said=[row.level for row in rows],
        min_spend_minor=settings.frequency_min_spend.get(found.account.currency, 0),
        new_creative=new_creative,
    )
    if decision.reset:
        if new_creative:
            for row in rows:
                if not row.answer:
                    row.answer, row.answered_at = FrequencyAnswer.CREATIVE_ADDED, now
        _close(rows, now=now)
        return None
    if decision.raise_to is None:
        return None
    _close([row for row in rows if RANK[row.level] < RANK[decision.raise_to]], now=now)
    row = FrequencyAlert(
        owner_id=owner.id,
        provider=found.account.provider,
        ad_account_id=found.account.id,
        adset_external_id=found.reading.adset_id,
        name=found.name,
        level=decision.raise_to,
        frequency=found.reading.frequency or 0,
        ctr_before_bp=found.ctr_before_bp,
        ctr_now_bp=found.ctr_now_bp,
        cost_minor=found.cost_minor,
        cost_usual_minor=found.cost_usual_minor,
        currency=found.account.currency,
    )
    db.add(row)
    db.flush()
    emit(
        db,
        owner_id=owner.id,
        name=EventName.FREQUENCY_ALERTED,
        aggregate_type="adset",
        aggregate_id=row.adset_external_id,
        payload={"level": row.level, "frequency": row.frequency},
    )
    return row


def _close(rows: list[FrequencyAlert], *, now: datetime) -> None:
    for row in rows:
        row.closed_at = now


def _price_after(db: Session, *, owner: User, now: datetime) -> None:
    """A week after each answer, what one result cost since."""
    a = FrequencyAlert
    rows = db.scalars(
        select(a).where(
            a.owner_id == owner.id,
            a.answered_at <= now - AFTER,
            a.answered_at >= now - AFTER * 4,
            a.cost_after_7d_minor.is_(None),
        )
    ).all()
    for row in rows:
        assert row.answered_at is not None
        row.cost_after_7d_minor = cost_between(
            db,
            owner=owner,
            account=row.ad_account,
            adset_id=row.adset_external_id,
            since=row.answered_at,
            until=row.answered_at + AFTER,
        )
    db.commit()


__all__ = ["check_frequency"]
