"""Account writes from a customer's card: old receipts, a password, deletion."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.common import tokens
from app.common.passwords import PasswordInvalid, make_password, validate_password
from app.modules.accounts.models import User
from app.modules.accounts.services import PurgeReport, purge_user
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.exceptions import (
    EmailMismatch,
    PasswordRefused,
    SuperuserOnly,
)
from app.modules.backoffice.services.journal import record
from app.modules.billing.exceptions import ReasonRequired
from app.modules.billing.selectors import orphaned_receipts
from app.modules.billing.services import attach_receipts


def attach_old_receipts(
    db: Session, *, customer: User, actor: User, reason: str
) -> int:
    """Attach the paid bills a deleted account on this address left behind.

    Grants nothing: the access those bills bought went with the old account.
    """
    if not reason.strip():
        raise ReasonRequired
    kept = orphaned_receipts(db, email=customer.email)
    attached = attach_receipts(db, invoices=kept, owner=customer) if kept else 0
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.RECEIPTS_ATTACHED,
        reason=reason,
        detail={"invoices": [invoice.number for invoice in kept]},
    )
    return attached


def set_customer_password(
    db: Session,
    *,
    customer: User,
    actor: User,
    new_password: str,
    reason: str,
    now: datetime,
) -> User:
    """Replace the password without the old one, and sign the customer out on
    every device. Neither the journal nor the event holds the password."""
    if not actor.is_superuser:
        raise SuperuserOnly
    if not reason.strip():
        raise ReasonRequired
    try:
        validate_password(
            new_password, email=customer.email, full_name=customer.full_name
        )
    except PasswordInvalid as exc:
        raise PasswordRefused(str(exc)) from exc
    customer.password = make_password(new_password)
    db.flush()
    emit(
        db,
        owner_id=customer.id,
        name=EventName.USER_PASSWORD_CHANGED,
        aggregate_type="user",
        aggregate_id=customer.id,
        payload={},
        occurred_at=now,
    )
    record(
        db, customer=customer, actor=actor, kind=ActionKind.PASSWORD_SET, reason=reason
    )
    tokens.revoke_all(subject=str(customer.id), now=now)
    return customer


def delete_account(
    db: Session, *, customer: User, actor: User, typed_email: str
) -> PurgeReport:
    """Erase this account the way the admin's purge does; keep paid bills.

    The address has to be typed back. The journal row is filed under the
    member of staff: the customer's own rows go with the account.
    """
    if typed_email.strip().lower() != customer.email.lower():
        raise EmailMismatch
    email = customer.email
    report = purge_user(db, user=customer, reason=f"office:{actor.email}")
    record(
        db,
        customer=actor,
        actor=actor,
        kind=ActionKind.ACCOUNT_PURGED,
        detail={
            "email": email,
            "rows": report.rows,
            "receipts_kept": report.receipts_kept,
        },
    )
    db.commit()
    return report
