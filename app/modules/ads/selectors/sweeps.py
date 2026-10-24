"""Which accounts the mirror sweeps visit, and what their last sync said."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from metaads import PROVIDER as META
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    MIRROR_SWEEP,
    NOT_RUNNING,
    SYNC_OUTCOME_KEY,
    SYNC_QUEUED,
    SYNC_RATE_LIMITED,
    SYNC_STARTED,
    SYNC_TRUNCATED,
    TODAY_SWEEP,
)
from app.modules.ads.models import Campaign
from app.modules.integrations.models import AdAccount


def _live_campaign_accounts() -> Select[Any]:
    return (
        select(Campaign.ad_account_id)
        .where(Campaign.delivery.not_in([str(d) for d in NOT_RUNNING]))
        .distinct()
    )


def _frequently(*, now: datetime) -> Select[Any]:
    from app.modules.billing.selectors import recently_entitled_owner_ids

    return select(AdAccount).where(
        or_(AdAccount.synced_at.is_(None), AdAccount.id.in_(_live_campaign_accounts())),
        AdAccount.is_active.is_(True),
        AdAccount.owner_id.in_(recently_entitled_owner_ids(now=now)),
    )


def frequently_swept_accounts(db: Session, *, now: datetime) -> list[AdAccount]:
    return list(db.scalars(_frequently(now=now)))


def frequently_swept_account_ids(db: Session, *, now: datetime) -> list[uuid.UUID]:
    query = _frequently(now=now).with_only_columns(AdAccount.id)
    return list(db.scalars(query))


def library_swept_account_ids(db: Session, *, now: datetime) -> list[uuid.UUID]:
    query = (
        _frequently(now=now)
        .where(AdAccount.provider == META)
        .with_only_columns(AdAccount.id)
    )
    return list(db.scalars(query))


def _nightly() -> Select[Any]:
    from app.modules.billing.selectors import subscribed_owner_ids

    return select(AdAccount).where(
        AdAccount.is_active.is_(True), AdAccount.owner_id.in_(subscribed_owner_ids())
    )


def nightly_swept_accounts(db: Session) -> list[AdAccount]:
    return list(db.scalars(_nightly()))


def nightly_swept_account_ids(db: Session) -> list[uuid.UUID]:
    return list(db.scalars(_nightly().with_only_columns(AdAccount.id)))


def nightly_due_account_ids(
    db: Session, *, now: datetime, hour: int
) -> list[uuid.UUID]:
    from app.modules.integrations.selectors import owners_at_hour

    rows = list(
        db.execute(_nightly().with_only_columns(AdAccount.id, AdAccount.owner_id))
    )
    due = owners_at_hour(db, owner_ids={owner for _, owner in rows}, now=now, hour=hour)
    return [pk for pk, owner in rows if str(owner) in due]


# -- what the last sync said ----------------------------------------------------------


def last_sync_outcomes(*, sweep: str, ad_account_ids: Iterable[Any]) -> dict[str, str]:
    keys = {
        SYNC_OUTCOME_KEY.format(sweep=sweep, account_id=pk): str(pk)
        for pk in ad_account_ids
    }
    found = cache.get_many(list(keys))
    return {keys[key]: str(word) for key, word in found.items()}


IN_FLIGHT = frozenset({SYNC_QUEUED, SYNC_STARTED})
UNUSABLE: Final = "unusable"
BUSY: Final = "busy"
RATE_LIMITED: Final = SYNC_RATE_LIMITED
TRUNCATED: Final = SYNC_TRUNCATED
FAILED: Final = "failed"
FAILURE_ORDER = (UNUSABLE, TRUNCATED, RATE_LIMITED, BUSY, FAILED)


@dataclass(frozen=True, slots=True)
class SyncProgress:
    known: bool
    in_flight: bool
    succeeded: bool
    failure: str


def sync_progress(*, ad_account_ids: Iterable[Any]) -> SyncProgress:
    ids = [str(pk) for pk in ad_account_ids]
    said = last_sync_outcomes(sweep=MIRROR_SWEEP, ad_account_ids=ids)
    words = [said[pk] for pk in ids if pk in said]
    failures = {_failure(word) for word in words} - {""}
    return SyncProgress(
        known=bool(ids) and len(words) == len(ids),
        in_flight=any(word in IN_FLIGHT for word in words),
        succeeded=any(word not in IN_FLIGHT and not _failure(word) for word in words),
        failure=next((word for word in FAILURE_ORDER if word in failures), ""),
    )


def _failure(word: str) -> str:
    if word in IN_FLIGHT:
        return ""
    if word in (BUSY, UNUSABLE):
        return word
    if word.startswith(FAILED):
        cause = word.partition(":")[2]
        return cause if cause in (TRUNCATED, RATE_LIMITED) else FAILED
    return ""


def today_in_flight(*, ad_account_ids: Iterable[Any]) -> bool:
    said = last_sync_outcomes(sweep=TODAY_SWEEP, ad_account_ids=ad_account_ids)
    return any(word in IN_FLIGHT for word in said.values())


def still_waiting(
    db: Session, *, owner: User, account_ids: Iterable[str], since: str
) -> bool:
    try:
        ids = sorted({uuid.UUID(pk) for pk in account_ids})
    except ValueError:
        return False
    accounts = list(
        db.scalars(
            select(AdAccount).where(
                AdAccount.owner_id == owner.id, AdAccount.id.in_(ids)
            )
        )
    )
    if not ids or len(accounts) != len(ids):
        return False
    stamps = [account.synced_at for account in accounts]
    now = "" if None in stamps else min(s for s in stamps if s).isoformat()
    progress = sync_progress(ad_account_ids=ids)
    mirror = since == now and (progress.in_flight or not progress.known)
    return mirror or today_in_flight(ad_account_ids=ids)
