"""Telling the provider, once a night, how the day's leads turned out.

**Once a night, not as it happens.** The provider cannot take an event back,
so the send waits until the owner's day is over and asks where each card
stands then. A card dragged into the wrong column and put back the same
afternoon is a mistake nobody outside the board hears of.

**Into the pixel of the lead's own ad account.** An account without one keeps
its rows pending; they age out of the window unsent and the dashboard says why.

A batch with one bad event is refused whole, so a refused batch is halved
until the bad row stands alone. Every other failure leaves the rows pending
for tomorrow.
"""

import logging
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from adskit import ExternalRef, LeadEventDTO, MinorUnits, registry
from adskit.errors import InvalidRequest, NotFound, ProviderError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.crypto import decrypt
from app.common.db import utcnow
from app.common.exceptions import DecryptionFailed
from app.modules.accounts.models import User
from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
from app.modules.integrations.models import AdAccount
from app.modules.integrations.selectors import owner_clocks, owners_at_hour
from app.modules.leads.constants import (
    SIGNAL_REPORT_HOUR,
    SIGNALS_PER_BATCH,
    SIGNALS_PER_RUN,
    SignalSource,
    SignalStatus,
)
from app.modules.leads.models import Lead, LeadSignal
from app.modules.leads.selectors.reads import reporting_dataset
from core.leads import event_key, is_reportable, stage_rank

logger = logging.getLogger(__name__)

LEAD_LEVEL = "lead"
DATASET_LEVEL = "dataset"
ERROR_KEPT = 500


def sweep_lead_signals(db: Session, *, now: datetime) -> int:
    """Queue tonight's send for every owner whose hour it is."""
    from app.modules.crm.selectors import running_owners
    from app.modules.leads.tasks import report_signals_task

    waiting = db.scalars(
        select(LeadSignal.owner_id)
        .where(LeadSignal.status == SignalStatus.PENDING)
        .distinct()
    )
    owners = {*waiting, *running_owners(db)}
    due = owners_at_hour(db, owner_ids=owners, now=now, hour=SIGNAL_REPORT_HOUR)
    for owner_id in due:
        report_signals_task.delay(owner_id)
    return len(due)


def report_signals(db: Session, *, owner_id: uuid.UUID | str, now: datetime) -> str:
    """Send one owner's finished days. A word for the log; never raises."""
    from app.modules.crm.services import collect_signals

    owner = db.get(User, uuid.UUID(str(owner_id)))
    if owner is None:
        return "gone"
    clock = owner_clocks(db, owner_ids=[owner.id])[str(owner.id)]
    today = now.astimezone(clock).replace(hour=0, minute=0, second=0, microsecond=0)
    collect_signals(db, owner=owner, until=today, now=now)
    db.commit()
    groups: dict[uuid.UUID, list[LeadSignal]] = defaultdict(list)
    for row in db.scalars(
        select(LeadSignal)
        .where(
            LeadSignal.owner_id == owner.id,
            LeadSignal.status == SignalStatus.PENDING,
            LeadSignal.occurred_at < today,
        )
        .order_by(LeadSignal.occurred_at)
        .limit(SIGNALS_PER_RUN)
    ):
        groups[row.ad_account_id].append(row)
    words = [
        _send_account(db, owner=owner, account_id=key, rows=rows, now=now)
        for key, rows in groups.items()
    ]
    db.commit()
    return ",".join(words) or "nothing_due"


def _send_account(
    db: Session,
    *,
    owner: User,
    account_id: uuid.UUID,
    rows: list[LeadSignal],
    now: datetime,
) -> str:
    account = db.get(AdAccount, account_id)
    if account is None:
        return "no_account"
    rehearsing = settings.ads_dry_run
    port = registry.get(account.provider).conversions
    window = port.report_window_days()
    ready: list[LeadSignal] = []
    for row in rows:
        if not _sendable(row.lead):
            if not rehearsing:
                row.status = SignalStatus.WITHDRAWN
        elif is_reportable(occurred_at=row.occurred_at, now=now, window_days=window):
            ready.append(row)
        elif not rehearsing:
            row.status = SignalStatus.EXPIRED
    if not ready:
        db.commit()
        return "nothing_ready"
    dataset = reporting_dataset(db, owner=owner, ad_account=account)
    if not dataset:
        db.commit()
        return "no_dataset"
    token = _token(account)
    if token is None:
        db.commit()
        return "connection_unusable"
    ready.sort(key=lambda row: (row.occurred_at, stage_rank(row.stage)))
    reference = ExternalRef(provider=account.provider, level=DATASET_LEVEL, id=dataset)
    sent = 0
    try:
        for start in range(0, len(ready), SIGNALS_PER_BATCH):
            sent += _send_batch(
                db,
                port=port,
                dataset=reference,
                rows=ready[start : start + SIGNALS_PER_BATCH],
                token=token,
                rehearsing=rehearsing,
                now=now,
            )
    except ProviderError as exc:
        db.commit()
        logger.warning("signals failed for %s: %s", owner.id, exc)
        return "provider_failed"
    db.commit()
    return f"rehearsed:{len(ready)}" if rehearsing else f"sent:{sent}"


def _send_batch(
    db: Session,
    *,
    port: object,
    dataset: ExternalRef,
    rows: Sequence[LeadSignal],
    token: str,
    rehearsing: bool,
    now: datetime,
) -> int:
    try:
        receipt = port.report_leads(  # type: ignore[attr-defined]
            dataset=dataset,
            events=[_event(row) for row in rows],
            token=token,
            dry_run=rehearsing,
        )
    except (InvalidRequest, NotFound) as exc:
        if len(rows) == 1:
            row = rows[0]
            row.status = SignalStatus.FAILED
            row.attempts += 1
            row.last_error = str(exc)[:ERROR_KEPT]
            logger.warning("Meta refused signal %s: %s", row.id, exc)
            return 0
        middle = len(rows) // 2
        return sum(
            _send_batch(
                db,
                port=port,
                dataset=dataset,
                rows=part,
                token=token,
                rehearsing=rehearsing,
                now=now,
            )
            for part in (rows[:middle], rows[middle:])
        )
    if rehearsing:
        return 0
    if receipt.accepted < len(rows):
        logger.info("Meta took %s of %s signals", receipt.accepted, len(rows))
    _stamp(db, rows=rows, dataset=dataset.id, trace=receipt.trace_id, now=now)
    db.commit()
    return len(rows)


def _stamp(
    db: Session,
    *,
    rows: Sequence[LeadSignal],
    dataset: str,
    trace: str,
    now: datetime,
) -> None:
    from app.modules.crm.services import note_signals_sent

    for row in rows:
        row.status = SignalStatus.SENT
        row.sent_at = now
        row.attempts += 1
        row.dataset_id = dataset
        row.trace_id = trace[:128]
        row.last_error = ""
    note_signals_sent(db, rows=rows, now=now)


def _sendable(lead: Lead) -> bool:
    return (
        bool(lead.leadgen_id)
        and not lead.is_test
        and not lead.is_organic
        and lead.anonymized_at is None
    )


def _token(account: AdAccount) -> str | None:
    connection = account.connection
    if connection.status not in USABLE_CONNECTION_STATUSES:
        return None
    try:
        return decrypt(connection.token_encrypted)
    except DecryptionFailed:
        logger.exception("connection %s could not be decrypted", connection.id)
        return None


def _event(row: LeadSignal) -> LeadEventDTO:
    provider = row.lead.provider
    external_id = row.lead.leadgen_id
    converted = row.stage == "converted" and row.value_minor is not None
    return LeadEventDTO(
        lead=ExternalRef(provider=provider, level=LEAD_LEVEL, id=external_id),
        stage=row.stage,
        occurred_at=row.occurred_at,
        event_id=event_key(
            provider=provider, lead_external_id=external_id, stage=row.stage
        ),
        value_minor=MinorUnits(row.value_minor) if converted else None,
        currency=row.currency if converted else "",
    )


def note_verdict(db: Session, *, owner: User, lead: Lead, status: str) -> None:
    """A lead marked by hand, when no card speaks for it."""
    from app.modules.crm.selectors import has_card, pair_of_lead

    if has_card(db, lead_id=lead.id):
        return
    pair = pair_of_lead(db, owner=owner, lead_id=lead.id)
    if pair is None:
        return
    withdraw_verdict(db, lead=lead)
    now = utcnow()
    row = db.scalar(
        select(LeadSignal).where(
            LeadSignal.lead_id == lead.id, LeadSignal.stage == status
        )
    )
    if row is None:
        db.add(
            LeadSignal(
                owner_id=lead.owner_id,
                lead_id=lead.id,
                ad_account_id=pair.account.id,
                stage=status,
                source=SignalSource.MANUAL,
                occurred_at=max(now, lead.submitted_at + timedelta(seconds=1)),
            )
        )
    elif row.status == SignalStatus.WITHDRAWN:
        row.status = SignalStatus.PENDING
        row.occurred_at = now
    db.flush()


def withdraw_verdict(db: Session, *, lead: Lead) -> None:
    for row in db.scalars(
        select(LeadSignal).where(
            LeadSignal.lead_id == lead.id,
            LeadSignal.source == SignalSource.MANUAL,
            LeadSignal.status == SignalStatus.PENDING,
        )
    ):
        row.status = SignalStatus.WITHDRAWN
    db.flush()


__all__ = [
    "note_verdict",
    "report_signals",
    "sweep_lead_signals",
    "withdraw_verdict",
]
