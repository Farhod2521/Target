"""The sales team's Google Sheet of sign-ups who did not pay.

Every minute, each account opened since the start date that has had five
minutes to pay and has not is added at the bottom of the sheet, once. An
account that pays afterwards stays in the sheet as it was.

The rows go to an Apps Script inside the sheet (deploy/signup_sheet.gs),
whose web app URL with its token is ``SIGNUP_SHEET_URL``: no Google Cloud
project and no key. Anything but "ok" back leaves the accounts unrecorded,
and the next minute sends them again.
"""

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import httpx
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
TIME_FORMAT: Final = "%d.%m.%Y %H:%M"
_ROLES: Final[dict[str, str]] = {
    str(role): label for role, label in ROLE_LABELS.items()
}
TIMEOUT_SECONDS: Final = 60.0


class NotWritten(Exception):
    """The script did not answer "ok"."""


def is_configured() -> bool:
    return bool(settings.signup_sheet_url)


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


def sheet_row(user: User) -> list[str]:
    return [
        user.date_joined.astimezone(ZONE).strftime(TIME_FORMAT),
        user.full_name,
        user.phone,
        user.email,
        _ROLES.get(user.role, user.role),
    ]


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
    try:
        send([sheet_row(user) for user in users])
    except (httpx.HTTPError, NotWritten) as exc:
        # The exception's own text can carry the URL, and the URL the token.
        logger.warning(
            "signup sheet: %d rows not written: %s %s",
            len(users),
            type(exc).__name__,
            exc if isinstance(exc, NotWritten) else _status(exc),
        )
        return 0
    db.add_all(SignupSheetRow(owner_id=user.id, written_at=now) for user in users)
    db.commit()
    return len(users)


def send(rows: Sequence[Sequence[str]]) -> None:
    """One POST to the sheet's script. Google answers a web app with a
    redirect to the script's output, which is followed."""
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
        answer = client.post(
            settings.signup_sheet_url,
            json={"headings": list(HEADINGS), "rows": [list(row) for row in rows]},
        )
    answer.raise_for_status()
    if answer.text.strip() != "ok":
        raise NotWritten(answer.text.strip()[:200])


def _status(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return str(exc.response.status_code)
    return ""
