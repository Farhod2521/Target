"""Account writes from a customer's card: old receipts, a password, a block,
deletion."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.common import tokens
from app.common.passwords import PasswordInvalid, make_password, validate_password
from app.modules.accounts.models import BlockReason, User
from app.modules.accounts.services import (
    PurgeReport,
    block_user,
    purge_user,
    unblock_user,
)
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.exceptions import (
    AlreadyBlocked,
    BlockReasonArchived,
    EmailMismatch,
    NotBlocked,
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


def block_customer(
    db: Session,
    *,
    customer: User,
    actor: User,
    reason: BlockReason,
    shown_to_user: bool,
    note: str,
    now: datetime,
) -> User:
    """Shut the account and sign the customer out on every device. The ads
    it launched here are stopped at Meta at once and deleted there 24 hours
    later, unless it is opened again first; ads made elsewhere are not touched.
    The reason is told to the customer at sign-in only when ``shown_to_user``;
    the note never is."""
    if reason.is_archived:
        raise BlockReasonArchived
    if not customer.is_active:
        raise AlreadyBlocked
    block_user(
        db,
        user=customer,
        reason=reason,
        shown_to_user=shown_to_user,
        note=note,
        actor=actor,
        now=now,
    )
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.ACCOUNT_BLOCKED,
        reason=f"{reason.name}: {note.strip()}" if note.strip() else reason.name,
        detail={"reason_id": str(reason.id), "shown_to_user": shown_to_user},
    )
    tokens.revoke_all(subject=str(customer.id), now=now)
    return customer


def unblock_customer(
    db: Session, *, customer: User, actor: User, reason: str, now: datetime
) -> User:
    """Open the account again; the customer signs in anew."""
    if not reason.strip():
        raise ReasonRequired
    if customer.is_active:
        raise NotBlocked
    unblock_user(db, user=customer, note=reason, actor=actor, now=now)
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.ACCOUNT_UNBLOCKED,
        reason=reason,
    )
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
