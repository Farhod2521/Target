"""The sales team's Google Sheet of sign-ups who did not pay.

Every minute, each account opened since the start date that has had five
minutes to pay and has not is added at the bottom of the sheet, once. An
account that pays afterwards stays in the sheet as it was.

The app writes as a service account (``GOOGLE_SERVICE_ACCOUNT``), so the
sheet only has to be shared with that account's email as Editor. A failed
write leaves the accounts unrecorded and the next minute tries again.
"""

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from googlekit import CellValue, GoogleError, SheetsClient, read_key, service_token
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.modules.accounts.constants import ROLE_LABELS
from app.modules.accounts.models import User
from app.modules.billing.constants import InvoiceStatus, SubscriptionStatus
from app.modules.billing.models import Invoice, Subscription
from app.modules.sales.models import SignupSheetRow

logger = logging.getLogger(__name__)

ZONE: Final = ZoneInfo("Asia/Tashkent")
# Accounts opened before this are never written: the list starts here.
STARTS_AT: Final = datetime(2026, 11, 10, tzinfo=ZONE)
PAY_WINDOW: Final = timedelta(minutes=5)
BATCH: Final = 500
LOCK_KEY: Final = "sales:signup-sheet"
LOCK_SECONDS: Final = 300
HEADINGS: Final = ("Ro'yxatdan o'tgan vaqti", "Ism", "Telefon", "Email", "Kim")


def is_configured() -> bool:
    return bool(settings.google_service_account and settings.signup_sheet_id)


def due_signups(db: Session, *, now: datetime, limit: int = BATCH) -> list[User]:
    """Owners who signed up since the start, five minutes ago or more, and have
    neither paid nor been given a running subscription, and are not written."""
    paid = exists().where(
        Invoice.owner_id == User.id, Invoice.status == str(InvoiceStatus.PAID)
    )
    subscribed = exists().where(
        Subscription.owner_id == User.id,
        Subscription.status == str(SubscriptionStatus.ACTIVE),
    )
    written = exists().where(SignupSheetRow.owner_id == User.id)
    return list(
        db.scalars(
            select(User)
            .where(
                User.date_joined >= STARTS_AT,
                User.date_joined <= now - PAY_WINDOW,
                User.crm_owner_id.is_(None),
                User.is_staff.is_(False),
                User.is_superuser.is_(False),
                User.is_active.is_(True),
                ~paid,
                ~subscribed,
                ~written,
            )
            .order_by(User.date_joined, User.id)
            .limit(limit)
        )
    )


def sheet_row(user: User) -> tuple[CellValue, ...]:
    return (
        user.date_joined.astimezone(ZONE),
        user.full_name,
        user.phone,
        user.email,
        ROLE_LABELS.get(user.role, user.role),
    )


def sweep_signup_sheet(db: Session, *, now: datetime) -> int:
    """Write what is due; the number of accounts written."""
    if not is_configured():
        return 0
    if not cache.add(LOCK_KEY, "1", LOCK_SECONDS):
        return 0
    try:
        return _write_due(db, now=now)
    finally:
        cache.delete(LOCK_KEY)


def _write_due(db: Session, *, now: datetime) -> int:
    users = due_signups(db, now=now)
    if not users:
        return 0
    first = db.scalar(select(exists().where(SignupSheetRow.owner_id.is_not(None))))
    rows: list[Sequence[CellValue]] = [] if first else [HEADINGS]
    rows.extend(sheet_row(user) for user in users)
    try:
        _append(rows)
    except (GoogleError, ValueError) as exc:
        logger.warning("signup sheet: %d rows not written: %s", len(users), exc)
        return 0
    db.add_all(SignupSheetRow(owner_id=user.id, written_at=now) for user in users)
    db.commit()
    return len(users)


def _append(rows: Sequence[Sequence[CellValue]]) -> None:
    key = read_key(settings.google_service_account)
    with SheetsClient(access_token=service_token(key=key)) as client:
        found = client.describe(spreadsheet_id=settings.signup_sheet_id)
        if not found.tabs:
            raise GoogleError("the signup sheet has no tab")
        client.append(
            spreadsheet_id=settings.signup_sheet_id,
            sheet_id=found.tabs[0].sheet_id,
            rows=rows,
        )
