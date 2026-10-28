"""Page writes from a customer's card: one past the plan, one sideways, and
the two that change a page's pairs.

All go through integrations' own writes, so every follow-up a page needs is
queued exactly as when the customer presses the button themselves.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.services.entitlement import Payment, money, pay
from app.modules.backoffice.services.journal import record
from app.modules.billing.services import grant_pages
from app.modules.integrations.exceptions import AlreadyEnabled
from app.modules.integrations.models import PageAccount
from app.modules.integrations.services.cabinet import (
    change_pair_account,
    enable_page,
    remove_page_pair,
    swap_page,
)


def add_page(
    db: Session,
    *,
    customer: User,
    page: PageAccount,
    payment: Payment | None,
    actor: User,
    reason: str,
    now: datetime,
) -> PageAccount:
    """One more slot and ``page`` switched on in it, even with a slot free:
    the press means "past the plan"."""
    if page.is_active:
        raise AlreadyEnabled
    subscription = grant_pages(
        db, owner=customer, pages=1, actor=actor, reason=reason, now=now
    )
    invoice = None
    if payment is not None:
        invoice = pay(
            db,
            customer=customer,
            plan=subscription.plan,
            days=0,
            payment=payment,
            actor=actor,
            reason=reason,
            now=now,
        )
    enable_page(db, user=customer, external_id=page.external_id)
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.PAGE_ADDED,
        reason=reason,
        detail={
            "page": page.external_id,
            "name": page.name,
            "extra": subscription.extra_pages,
            **money(invoice),
        },
    )
    return page


def move_page(
    db: Session,
    *,
    customer: User,
    source: PageAccount,
    target: PageAccount,
    actor: User,
    reason: str,
    now: datetime,
) -> PageAccount:
    """Hand ``source``'s slot to ``target``; nothing the source collected moves."""
    swap_page(db, source=source, target=target, actor=actor, now=now)
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.PAGE_MOVED,
        reason=reason,
        detail={
            "from": source.external_id,
            "from_name": source.name,
            "to": target.external_id,
            "to_name": target.name,
        },
    )
    return target


def change_page_account(
    db: Session,
    *,
    customer: User,
    page: PageAccount,
    current: str,
    target: str,
    actor: User,
    reason: str,
) -> PageAccount:
    """Move one of the page's pairs to another of the account's ad accounts.

    ``current`` names the pair by its account, empty for a page nobody paired
    yet. Campaigns already made stay where they were made.
    """
    pair = change_pair_account(
        db,
        owner=customer,
        page_external_id=page.external_id,
        from_external_id=current,
        to_external_id=target,
        actor=actor,
    )
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.PAGE_ACCOUNT_CHANGED,
        reason=reason,
        detail={
            "page": page.external_id,
            "name": page.name,
            "from": current,
            "to": pair.ad_account.external_id,
            "to_name": pair.ad_account.name,
        },
    )
    return page


def remove_page_account(
    db: Session,
    *,
    customer: User,
    page: PageAccount,
    account: str,
    actor: User,
    reason: str,
) -> PageAccount:
    """Take one of the page's pairs away; the page and the account stay."""
    remove_page_pair(
        db,
        owner=customer,
        page_external_id=page.external_id,
        account_external_id=account,
        actor=actor,
    )
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.PAGE_PAIR_REMOVED,
        reason=reason,
        detail={"page": page.external_id, "name": page.name, "account": account},
    )
    return page
