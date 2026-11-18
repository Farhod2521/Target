"""The product's own plans and prices, for the assistant to quote.

Without this the assistant told a client «I cannot see the plan's price» and
«I do not know the dollar rate» - both are things the product shows on its
own Tarif page. Read-only; the prices are the ones this person may buy now
(Start only as a first purchase), with their discount if Sales gave one.
"""

from datetime import datetime
from typing import Final

from sqlalchemy.orm import Session

from app.common.money import format_minor
from app.modules.accounts.models import User

TAGLINE_CHARS: Final = 120


def plans_text(db: Session, *, owner: User | None, now: datetime) -> str:
    from app.modules.billing.selectors.display import usd_rate
    from app.modules.billing.selectors.plans import is_first_only, sellable_plans

    lines = ["## Plans this person may buy (on the «Tarif» page)"]
    for plan in sellable_plans(db, owner=owner):
        price = format_minor(amount_minor=plan.price, currency=plan.currency)
        parts = [f"- «{plan.name}»: {price} for {plan.period_days} days"]
        if is_first_only(plan):
            parts.append("sold once, only as the first purchase")
        parts.append(f"{plan.included_pages} page(s) included")
        if plan.extra_page_price:
            parts.append(
                "each extra page "
                + format_minor(amount_minor=plan.extra_page_price, currency=plan.currency)
            )
        if plan.crm_seat_price:
            parts.append(
                f"CRM: {plan.crm_free_seats} manager free, each more "
                + format_minor(amount_minor=plan.crm_seat_price, currency=plan.currency)
            )
        if plan.tagline:
            parts.append(plan.tagline[:TAGLINE_CHARS])
        lines.append(" · ".join(parts))
    if len(lines) == 1:
        lines.append("- none is on sale right now")

    if owner is not None:
        lines += ["", *_own(db, owner=owner, now=now)]

    rate = usd_rate()
    lines.append("")
    if rate is not None and rate[0]:
        dated = f", {rate[1]}" if rate[1] else ""
        rate_words = f"{rate[0]:,.0f}".replace(",", " ")
        lines.append(
            f"## Dollar rate\n- 1 USD = {rate_words} so'm (Central Bank of "
            f"Uzbekistan{dated}). Meta's ad spend is in the ad account's "
            "currency; this rate turns it into so'm approximately - the bank "
            "charges at its own rate."
        )
    else:
        lines.append("## Dollar rate\n- not available right now")
    return "\n".join(lines)


def _own(db: Session, *, owner: User, now: datetime) -> list[str]:
    from app.modules.billing.selectors import live_subscription
    from app.modules.boards.offer import live_offer

    lines = ["## This person"]
    subscription = live_subscription(db, owner=owner)
    if subscription is None:
        lines.append("- no live plan")
    else:
        lines.append(
            f"- on «{subscription.plan.name}» ({subscription.status}) until "
            f"{subscription.expires_at:%Y-%m-%d}"
        )
    offer = live_offer(db, owner_id=owner.id, now=now)
    if offer is not None:
        hours = max(1, int((offer.ends_at - now).total_seconds() // 3600))
        lines.append(
            f"- a personal discount of {offer.percent}% on a full plan (not "
            f"Start), {hours} more hour(s)"
            + (
                f", then {offer.next_percent}%"
                if offer.next_percent
                else ""
            )
            + "; it is applied on the «Tarif» page by itself."
        )
    return lines


__all__ = ["plans_text"]
