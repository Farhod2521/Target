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
from app.modules.integrations.models import AdAccount

OK: Final = "OK"
PROBLEM: Final = "PROBLEM"
RECENT_BILLS: Final = 3
DELIVERY_WINDOW: Final = timedelta(days=7)
STALE_SYNC: Final = timedelta(hours=24)
PLAN_ENDS_SOON_DAYS: Final = 3
# Where the person finds it, as a place key (``app.common.places``): the
# answer shows its name and links it - never an address.
CONNECT: Final = "[[boshqaruv]]"


def account_health(db: Session, *, owner: User, scope: PageScope, now: datetime) -> str:
    """Every check, in the order a person would ask about them."""
    lines: list[str] = []
    for title, rows in (
        ("Setup", _setup(db, owner=owner)),
        ("Plan and payments", _plan(db, owner=owner, now=now)),
        ("Card and autopay", _card(db, owner=owner, now=now)),
        ("Account", _block(db, owner=owner)),
        ("Facebook connection", _connection(db, owner=owner)),
        ("Ad accounts", _ad_accounts(db, owner=owner, now=now)),
        ("Lead delivery", _delivery(db, owner=owner, now=now)),
        (
            "Waiting on the cabinet's list",
            _waiting(db, owner=owner, scope=scope, now=now),
        ),
        ("Request to Support", _support(db, owner=owner, now=now)),
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
                fix="choose and pay a plan on [[obuna]].",
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
                fix="renew on [[obuna]] before it ends." if soon else "",
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
                    fix="pay it on [[obuna]]; if the money left the card and the "
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


# The steps of «Tayyorgarlik» as its screen names them.
_STEP_NAMES: Final[dict[str, str]] = {
    "connect": "Meta akkauntini ulash",
    "page": "sahifani tanlash",
    "ad_account": "reklama akkauntini tanlash",
    "profile": "biznes profili (nomi va turi)",
    "leads": "lidlarni ulash",
    "telegram": "Telegram botni ulash",
    "pixel": "piksel (ixtiyoriy)",
}
_STUCK: Final[dict[str, str]] = {
    "connect": "Meta is connected without every permission it was asked for - "
    "connect again and tick every permission",
    "ad_account": "Meta shows no ad account on the connected profile",
    "page": "Meta shows no Facebook page on the connected profile",
    "leads": "the page's lead terms (Meta's «leadgen terms») are not accepted",
}


def _setup(db: Session, *, owner: User) -> list[str]:
    """«Tayyorgarlik»: said only while it is unfinished - a finished one
    has nothing to report."""
    from app.modules.billing.selectors.subscription import setup_pending
    from app.modules.onboarding.selectors import setup_overview

    if not setup_pending(db, owner=owner):
        return []
    overview = setup_overview(db, owner=owner)
    lines = [
        _line(
            PROBLEM,
            f"setup on [[tayyorgarlik]] is not finished: "
            f"{overview.done} of {overview.total} steps done.",
        )
    ]
    for step in overview.steps:
        name = _STEP_NAMES.get(step.id, step.id)
        if step.state == "done":
            continue
        if step.state == "attention":
            lines.append(
                _line(
                    PROBLEM,
                    f"step «{name}» is stuck: {_STUCK.get(step.id, 'it needs a look')}.",
                )
            )
        elif step.state == "current":
            lines.append(_line(PROBLEM, f"next step: «{name}»."))
        elif step.state == "optional":
            lines.append(_line(OK, f"step «{name}» is optional and not done."))
        else:
            lines.append(_line(OK, f"step «{name}» waits for the step before it."))
    if overview.can_finish:
        lines.append(
            _line(
                PROBLEM,
                "the required choices are made, so «Yakunlash» can be pressed "
                "now; the other sections of the cabinet open after it, and the "
                "steps left can be done later.",
                fix="press «Yakunlash» on [[tayyorgarlik]].",
            )
        )
    return lines


def _card(db: Session, *, owner: User, now: datetime) -> list[str]:
    """The bound card and whether it renews the plan by itself."""
    from paykit.multicard import CHARGED, DECLINED, NEEDS_CODE

    from app.modules.autopay.constants import CHARGE_LEAD, MAX_ATTEMPTS
    from app.modules.autopay.selectors import active_card
    from app.modules.autopay.services import autopay_on
    from app.modules.billing.selectors import live_subscription

    if not autopay_on():
        return []
    card = active_card(db, owner=owner)
    if card is None:
        return [
            _line(
                OK,
                "no card is bound, so nothing renews by itself; a plan is "
                "paid by hand, and the pay dialog binds a card on the way.",
            )
        ]
    bound = f" since {card.bound_at:%Y-%m-%d}" if card.bound_at else ""
    lines = [
        _line(
            OK,
            f"card {card.ps.upper()} {card.pan} is bound{bound}; autopay is "
            f"{'on' if card.autopay else 'off'}.",
        )
    ]
    subscription = live_subscription(db, owner=owner)
    if (
        card.autopay
        and subscription is not None
        and subscription.canceled_at is None
        and subscription.plan.price
    ):
        lines.append(
            _line(
                OK,
                f"the card is charged for «{subscription.plan.name}» from "
                f"{subscription.expires_at - CHARGE_LEAD:%Y-%m-%d}, a day "
                "before the plan ends; extra pages and manager seats in "
                "use are renewed with it. The bill is made that day, so its "
                "sum is the one shown on [[obuna]].",
            )
        )
    if not card.autopay and subscription is not None:
        lines.append(
            _line(
                OK,
                f"the subscription was stopped: the plan runs to "
                f"{subscription.expires_at:%Y-%m-%d} and is not renewed by "
                "itself.",
                fix="«Obunani tiklash» on [[obuna]] turns autopay back on.",
            )
        )
    # An attempt is for one term; once that term was paid another way, its
    # refusal is history.
    current = subscription is None or card.charge_term == subscription.expires_at
    if card.last_charge_outcome in (DECLINED, NEEDS_CODE) and current:
        when = f" on {card.last_charge_at:%Y-%m-%d}" if card.last_charge_at else ""
        left = max(0, MAX_ATTEMPTS - card.charge_attempts)
        again = (
            f" It is tried again {left} more time(s), a day apart."
            if card.last_charge_outcome == DECLINED and left
            else " It is not tried again by itself."
        )
        lines.append(
            _line(
                PROBLEM,
                f"the last automatic charge{when} did not go through: "
                f"{card.last_charge_error or 'the bank refused it.'}{again}",
                fix="pay the plan by hand on [[obuna]], or bind another card there.",
            )
        )
    elif card.last_charge_outcome == CHARGED and card.last_charge_at:
        lines.append(
            _line(
                OK,
                f"the last automatic charge on {card.last_charge_at:%Y-%m-%d} went through.",
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
    from app.modules.integrations.constants import LINKED_CONNECTION_STATUSES
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
                fix=f"connect it on {CONNECT}, block «Ulanishlar», «Meta ulanishi» → «Ulash».",
            )
        ]
    lines: list[str] = []
    name = connection.external_user_name or "a Facebook profile"
    if connection.status not in LINKED_CONNECTION_STATUSES:
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
                fix=f"reconnect on {CONNECT}, «Meta ulanishi» → «Qayta ulash», with the same profile.",
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
                fix=f"reconnect on {CONNECT} («Qayta ulash») and leave every permission switched on.",
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


# What Meta's standing of an ad account means, said once for the model.
_STANDING_WORDS: Final = {
    "payment_failed": (
        "Meta could not take the payment for it; its adverts are stopped "
        "until the debt is paid"
    ),
    "disabled_payment": "Meta switched it off over a payment",
    "payment_grace": (
        "a payment did not go through; Meta gives a grace period - the "
        "adverts still run, but stop if it is not paid"
    ),
    "payment_pending": "Meta is still settling a payment on it",
    "review": "Meta is reviewing the account; adverts may not run meanwhile",
    "disabled": "Meta disabled it",
    "closed": "it is closed",
}
_MONEY_STANDINGS: Final = frozenset(
    {"payment_failed", "disabled_payment", "payment_grace", "payment_pending"}
)
BILLING_PATH: Final = (
    "Meta Business Suite → «Billing & payments» (To'lovlar) → "
    "«Payment settings», this ad account chosen at the top"
)


def _money_fix(row: AdAccount) -> str:
    from metaads.accounts import billing_url

    act = (
        "add money to its prepaid balance"
        if row.prepaid
        else "pay the debt («Pay now») or add another Visa/Mastercard that "
        "allows international payments in USD"
    )
    return (
        f"open {BILLING_PATH} - address, may be written out as it is: "
        f"{billing_url(row.external_id)} - "
        f"and {act}, signed in with a Facebook profile that manages this ad "
        "account. If the card has money and the bank allowed it, the bank "
        "or a person in Support settles the rest."
    )


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
        standing = row.standing or ""
        said = _STANDING_WORDS.get(standing)
        if said is not None:
            faults.append(said)
            if standing in _MONEY_STANDINGS:
                fix = fix or _money_fix(row)
            elif standing == "review":
                fix = (
                    fix
                    or "wait for Meta's review; Account Quality (facebook.com/accountquality) shows it."
                )
            else:
                fix = (
                    fix
                    or "ask Meta to review it in Account Quality (facebook.com/accountquality); if Meta does not open it, it needs a person."
                )
        elif row.may_advertise is False or row.payment_due:
            faults.append(
                "Meta does not let it advertise right now"
                + (f" (status {row.account_status})" if row.account_status else "")
            )
            fix = fix or (
                _money_fix(row)
                if row.payment_due
                else "open the ad account in Ads Manager and settle what Meta asks there."
            )
        if standing in _MONEY_STANDINGS and row.balance_minor > 0:
            faults.append(
                "owed to Meta: "
                + format_minor(amount_minor=row.balance_minor, currency=row.currency)
            )
        if 0 < row.spend_cap_minor <= row.amount_spent_minor:
            faults.append(
                "its account spending limit is used up ("
                + format_minor(amount_minor=row.spend_cap_minor, currency=row.currency)
                + "); Meta shows nothing more until it is raised"
            )
            fix = fix or (
                f"raise or remove «Account spending limit» on {BILLING_PATH}."
            )
        if row.synced_at is not None and now - row.synced_at > STALE_SYNC:
            faults.append(f"figures last synced {row.synced_at:%Y-%m-%d %H:%M} UTC")
        kind = " (prepaid balance)" if row.prepaid else ""
        if faults:
            lines.append(
                _line(
                    PROBLEM,
                    f"ad account «{name}»{kind}: {'; '.join(faults)}.",
                    fix=fix,
                )
            )
        else:
            lines.append(
                _line(OK, f"ad account «{name}» ({row.currency}){kind} can advertise.")
            )
    if not lines:
        lines.append(
            _line(
                PROBLEM,
                "no ad account is switched on in the subscription.",
                fix=f"switch one on on {CONNECT}: «Obunaga qo'shish» beside the ad account.",
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
            _line(OK, "Google Sheets is not connected (leads are in «CRM & Lidlar»).")
        )
    elif sheet.status == SheetStatus.BROKEN:
        lines.append(
            _line(
                PROBLEM,
                f"Google Sheets delivery is broken ({sheet.broken_reason or sheet.last_error_code or 'no reason stored'}) - new leads are not written to the sheet.",
                fix="open «CRM & Lidlar» → «Google jadval» and reconnect; leads kept meanwhile are written after that.",
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
                    fix="add the bot back to that group or channel as an admin, then link it again in «CRM & Lidlar» → «Telegramga uzatish».",
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
                    f"{count} lead(s) could not be delivered to {label} in the last 7 days. They are safe in «CRM & Lidlar».",
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


def _support(db: Session, *, owner: User, now: datetime) -> list[str]:
    from app.modules.assistant.selectors.support_request import (
        request_lines,
        support_request,
    )

    return request_lines(support_request(db, owner=owner, now=now), now=now)


__all__ = ["OK", "PROBLEM", "account_health"]
