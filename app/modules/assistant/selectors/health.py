"""The account's own state, for the assistant to find what is wrong.

Read-only, and from what the product has already stored: nothing here asks
Meta, Google or Telegram anything. Each line is a fact, marked ``OK`` or
``PROBLEM``, with the screen that fixes it where there is one - so the model
names a cause the product can stand behind, not one it guessed.
"""

from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope

OK: Final = "OK"
PROBLEM: Final = "PROBLEM"
RECENT_BILLS: Final = 3
DELIVERY_WINDOW: Final = timedelta(days=7)
STALE_SYNC: Final = timedelta(hours=24)
PLAN_ENDS_SOON_DAYS: Final = 3


def account_health(db: Session, *, owner: User, scope: PageScope, now: datetime) -> str:
    """Every check, in the order a person would ask about them."""
    lines: list[str] = []
    for title, rows in (
        ("Plan and payments", _plan(db, owner=owner, now=now)),
        ("Account", _block(db, owner=owner)),
        ("Facebook connection", _connection(db, owner=owner)),
        ("Ad accounts", _ad_accounts(db, owner=owner, now=now)),
        ("Lead delivery", _delivery(db, owner=owner, now=now)),
        (
            "Waiting on the cabinet's list",
            _waiting(db, owner=owner, scope=scope, now=now),
        ),
    ):
        lines += [f"## {title}", *(rows or [f"- {OK}: nothing to report"]), ""]
    return "\n".join(lines).rstrip()


def _line(mark: str, words: str, *, fix: str = "") -> str:
    return f"- {mark}: {words}" + (f" Fix: {fix}" if fix else "")


def _plan(db: Session, *, owner: User, now: datetime) -> list[str]:
    from app.modules.billing.constants import InvoiceStatus
    from app.modules.billing.selectors import days_left, live_subscription
    from app.modules.billing.selectors.invoices import invoice_history

    lines: list[str] = []
    subscription = live_subscription(db, owner=owner)
    if subscription is None:
        lines.append(
            _line(
                PROBLEM,
                "no live plan - the assistant, launches and reports are closed.",
                fix="choose and pay a plan on Tarif.",
            )
        )
    else:
        left = days_left(subscription=subscription, now=now)
        soon = left is not None and left <= PLAN_ENDS_SOON_DAYS
        lines.append(
            _line(
                PROBLEM if soon else OK,
                f"plan «{subscription.plan.name}», status {subscription.status}, "
                f"days left: {left if left is not None else 'unknown'}.",
                fix="renew on Tarif before it ends." if soon else "",
            )
        )
    for bill in list(invoice_history(db, owner=owner))[:RECENT_BILLS]:
        amount = format_minor(amount_minor=bill.amount_minor, currency=bill.currency)
        when = bill.paid_at or bill.created_at
        if bill.status == InvoiceStatus.PAID:
            lines.append(
                _line(OK, f"bill {bill.number}: {amount}, paid {when:%Y-%m-%d}.")
            )
        elif bill.status in (InvoiceStatus.PENDING, InvoiceStatus.HELD):
            lines.append(
                _line(
                    PROBLEM,
                    f"bill {bill.number}: {amount}, opened {when:%Y-%m-%d}, "
                    f"status {bill.status} - not paid, or the payment has not arrived.",
                    fix="pay it on Tarif; if the money left the card and the "
                    "bill is still open, it needs a person.",
                )
            )
        else:
            lines.append(
                _line(
                    OK,
                    f"bill {bill.number}: {amount}, {bill.status} ({when:%Y-%m-%d}).",
                )
            )
    return lines


def _block(db: Session, *, owner: User) -> list[str]:
    from app.modules.accounts.models import AccountBlock

    block = db.scalar(
        select(AccountBlock)
        .where(AccountBlock.owner_id == owner.id, AccountBlock.lifted_at.is_(None))
        .order_by(AccountBlock.blocked_at.desc())
        .limit(1)
    )
    if block is None:
        return [_line(OK, "the account is not blocked.")]
    reason = block.reason
    shown = block.shown_to_user and reason is not None
    said = (reason.message_uz or reason.name) if shown else "not shown to the client"
    return [
        _line(
            PROBLEM,
            f"the account is blocked since {block.blocked_at:%Y-%m-%d}. Reason: {said}.",
            fix="needs a person - only Support can open it again.",
        )
    ]


def _connection(db: Session, *, owner: User) -> list[str]:
    from app.modules.integrations.constants import ConnectionStatus
    from app.modules.integrations.selectors.connection import (
        meta_connection,
        missing_scopes,
    )

    connection = meta_connection(db, owner=owner)
    if connection is None:
        return [
            _line(
                PROBLEM,
                "Facebook is not connected.",
                fix="connect it on Ulanishlar ('Meta'ni ulash').",
            )
        ]
    lines: list[str] = []
    name = connection.external_user_name or "a Facebook profile"
    if connection.status != ConnectionStatus.ACTIVE:
        lines.append(
            _line(
                PROBLEM,
                f"the Facebook connection ({name}) is {connection.status}"
                + (
                    f", error {connection.last_error_code}"
                    if connection.last_error_code
                    else ""
                )
                + " - nothing can be launched, changed or synced.",
                fix="reconnect on Ulanishlar ('Meta'ni qayta ulash') with the same profile.",
            )
        )
    else:
        lines.append(_line(OK, f"Facebook is connected as {name}."))
    lacking = missing_scopes(db, owner=owner)
    if lacking:
        lines.append(
            _line(
                PROBLEM,
                f"permissions not given at connection: {', '.join(lacking)}.",
                fix="reconnect on Ulanishlar and leave every permission switched on.",
            )
        )
    if connection.action_required_at is not None:
        lines.append(
            _line(
                PROBLEM,
                "Meta asks the profile's owner to confirm something in Facebook "
                f"itself (since {connection.action_required_at:%Y-%m-%d}).",
                fix="open Facebook with that profile and finish what it asks, then reconnect.",
            )
        )
    return lines


def _ad_accounts(db: Session, *, owner: User, now: datetime) -> list[str]:
    from app.modules.chat.selectors.scope import subscribed_accounts

    lines: list[str] = []
    for row in subscribed_accounts(db, owner=owner):
        name = row.name or row.external_id
        faults: list[str] = []
        fix = ""
        if row.reach_lost_at is not None:
            faults.append(
                f"the connected Facebook profile cannot reach it since {row.reach_lost_at:%Y-%m-%d}"
            )
            fix = "reconnect with the profile that manages this ad account, or give it the role in Business Manager."
        if row.may_advertise is False:
            faults.append(
                "Meta does not let it advertise right now"
                + (f" (status {row.account_status})" if row.account_status else "")
            )
            fix = (
                fix
                or "open the ad account in Ads Manager and settle what Meta asks there."
            )
        if row.payment_due:
            faults.append("Meta has an unpaid amount on it")
            fix = fix or "pay it in Ads Manager, on the ad account's payments page."
        if row.synced_at is not None and now - row.synced_at > STALE_SYNC:
            faults.append(f"figures last synced {row.synced_at:%Y-%m-%d %H:%M} UTC")
        if faults:
            lines.append(
                _line(PROBLEM, f"ad account «{name}»: {'; '.join(faults)}.", fix=fix)
            )
        else:
            lines.append(
                _line(OK, f"ad account «{name}» ({row.currency}) can advertise.")
            )
    if not lines:
        lines.append(
            _line(
                PROBLEM,
                "no ad account is switched on in the subscription.",
                fix="switch one on on Ulanishlar.",
            )
        )
    return lines


def _delivery(db: Session, *, owner: User, now: datetime) -> list[str]:
    from app.modules.destinations.constants import (
        Channel,
        DeliveryStatus,
        LeadChatStatus,
        SheetStatus,
    )
    from app.modules.destinations.models import LeadChat, LeadDelivery, SheetLink

    lines: list[str] = []
    sheet = db.scalar(select(SheetLink).where(SheetLink.owner_id == owner.id))
    if sheet is None or sheet.status == SheetStatus.DISCONNECTED:
        lines.append(
            _line(OK, "Google Sheets is not connected (leads are in Mijozlar).")
        )
    elif sheet.status == SheetStatus.BROKEN:
        lines.append(
            _line(
                PROBLEM,
                f"Google Sheets delivery is broken ({sheet.broken_reason or sheet.last_error_code or 'no reason stored'}) - new leads are not written to the sheet.",
                fix="open the Google Sheets panel in Mijozlar and reconnect; leads kept meanwhile are written after that.",
            )
        )
    else:
        last = (
            f", last written {sheet.last_delivered_at:%Y-%m-%d %H:%M} UTC"
            if sheet.last_delivered_at
            else ""
        )
        lines.append(_line(OK, f"Google Sheets is {sheet.status}{last}."))
    chats = list(db.scalars(select(LeadChat).where(LeadChat.owner_id == owner.id)))
    for chat in chats:
        title = chat.title or "Telegram chat"
        if chat.status == LeadChatStatus.BROKEN:
            lines.append(
                _line(
                    PROBLEM,
                    f"Telegram chat «{title}» stopped receiving leads ({chat.broken_reason or chat.last_error or 'no reason stored'}).",
                    fix="add the bot back to that group or channel as an admin, then link it again in Mijozlar.",
                )
            )
        else:
            lines.append(_line(OK, f"Telegram chat «{title}» receives leads."))
    if not chats:
        lines.append(_line(OK, "no Telegram group or channel is linked for leads."))
    since = now - DELIVERY_WINDOW
    failed = dict(
        db.execute(
            select(LeadDelivery.channel, func.count())
            .where(
                LeadDelivery.owner_id == owner.id,
                LeadDelivery.status == DeliveryStatus.FAILED,
                LeadDelivery.sent_at >= since,
            )
            .group_by(LeadDelivery.channel)
        ).all()
    )
    for channel, label in (
        (Channel.SHEETS, "Google Sheets"),
        (Channel.TELEGRAM, "Telegram"),
    ):
        count = int(failed.get(str(channel), 0) or 0)
        if count:
            lines.append(
                _line(
                    PROBLEM,
                    f"{count} lead(s) could not be delivered to {label} in the last 7 days. They are safe in Mijozlar.",
                )
            )
    return lines


def _waiting(db: Session, *, owner: User, scope: PageScope, now: datetime) -> list[str]:
    """The cabinet's own list, as the ``open_problems`` look-up reads it."""
    from app.modules.chat.selectors.lookups import answer_lookup
    from core.chat.lookup_arguments import Nothing

    text = answer_lookup(
        db, owner=owner, name="open_problems", arguments=Nothing(), scope=scope, now=now
    )
    rows = [line for line in text.splitlines() if line.startswith("- ")]
    return rows or [_line(OK, "nothing is waiting.")]


__all__ = ["OK", "PROBLEM", "account_health"]
