"""The owner's invite link, the friends it brought, and the wallet.

Read the way the «Referal» page («Taklif qilish», /app/referrals/) reads it:
the same balance, the same rule for taking money out. Counts and sums only -
an invited friend is never named.
"""

from datetime import datetime
from typing import Final

from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.money import format_minor
from app.modules.accounts.models import User

RECENT: Final = 3
PAGE: Final = "«Taklif qilish» (/app/referrals/)"


def referrals_text(db: Session, *, owner: User, now: datetime) -> str:
    from app.modules.referrals import selectors
    from app.modules.referrals.constants import (
        PAYOUT_STATUS_LABELS,
        REFERRAL_PERCENT,
        ReferralMode,
    )
    from app.modules.referrals.selectors.eligibility import referral_mode

    lines = [f"## Invite link and wallet (on {PAGE})"]
    if referral_mode(db, owner_id=owner.id) == ReferralMode.CLOSED:
        lines.append(
            "- the invite programme is switched off for this account by the "
            "team; money already in the wallet stays and is not spent."
        )
    code = selectors.code_of(db, owner=owner)
    if code is not None:
        lines.append(
            f"- their invite link: {selectors.invite_link(code=str(code.code))} - "
            f"a friend who signs up through it and pays brings them "
            f"{REFERRAL_PERCENT}% of that first payment into the wallet."
        )
    friends = selectors.invited_users(db, owner=owner)
    if friends:
        rows = selectors.invited_rows(db, owner=owner, bindings=friends, now=now)
        paid = sum(1 for row in rows if row.state == "paid")
        trial = sum(1 for row in rows if row.state == "trial")
        lines.append(
            f"- friends signed up through it: {len(rows)}; paid: {paid}; on a "
            f"trial: {trial}; not paid yet: {len(rows) - paid - trial}"
        )
    else:
        lines.append("- nobody has signed up through their link yet")

    balances = selectors.wallet_balance(db, owner=owner)
    if not balances:
        lines.append("- wallet: empty, nothing earned yet")
    for row in balances:

        def money(amount: int, currency: str = row.currency) -> str:
            return format_minor(amount_minor=amount, currency=currency)

        lines.append(
            f"- wallet ({row.currency}): available {money(row.available_minor)}; "
            f"earned in all {money(row.earned_minor)}; spent on plan payments "
            f"{money(row.spent_minor)}; taken out to a card {money(row.paid_minor)}"
            + (
                f"; asked to take out and being checked {money(row.held_minor)}"
                if row.held_minor
                else ""
            )
        )
    if any(row.available_minor > 0 for row in balances):
        lines.append(
            "- wallet money pays for a plan: on the pay dialog they tick the "
            "balance, and the bill is that much smaller."
        )
        if not settings.withdrawals_open:
            lines.append(
                "- taking money out to a card is closed for now for everyone; "
                "the money stays in the wallet."
            )
        elif selectors.may_withdraw(db, owner=owner):
            lines.append(
                f"- they may ask to take it out to a card on {PAGE} "
                "(«Pul yechish so'rovini yuborish»); there is no smallest sum."
            )
        else:
            lines.append(
                "- taking it out to a card opens once a paid plan is active; "
                "it can be spent on a plan payment at any time."
            )
    labels = {str(status): words for status, words in PAYOUT_STATUS_LABELS.items()}
    for ask in selectors.payout_history(db, owner=owner)[:RECENT]:
        lines.append(
            f"- a request to take out {format_minor(amount_minor=ask.amount_minor, currency=ask.currency)}"
            f" on {ask.created_at:%Y-%m-%d}: "
            f"{labels.get(ask.status, ask.status)}"
        )
    return "\n".join(lines)


__all__ = ["referrals_text"]
