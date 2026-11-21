"""The Statistika screen as the assistant reads it, block by block.

Every figure is the screen's own selector
(:mod:`app.modules.backoffice.selectors.stats`), written out as lines; only
the blocks asked for are read. Each block says whether it is "in the
window", "as of the window's end" or "now", as the screen does.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.common.money import format_minor
from app.modules.backoffice.selectors import stats
from app.modules.backoffice.selectors.dashboard import Window
from app.modules.officeai.selectors.facts import window_of
from core.officeai.tools import Statistics


def _money(amount: int, currency: str) -> str:
    return format_minor(amount_minor=amount, currency=currency)


def _usd(micros: int) -> str:
    """Claude's cost is kept in micros of a cent; shown in dollars."""
    return f"${micros / stats.USD_MICROS:,.2f}".replace(",", " ")


def _under(heading: str, rows: list[str]) -> list[str]:
    """A heading with its rows, or nothing when there are none."""
    return [heading, *rows] if rows else []


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value}%"


@dataclass(slots=True)
class _Read:
    """One call's reads: the paid bills are walked once, however many blocks
    need them."""

    db: Session
    window: Window
    now: datetime
    _buyers: dict[str, stats.Buyer] | None = field(default=None, repr=False)
    _people: dict[str, Any] | None = field(default=None, repr=False)
    _businesses: dict[str, Any] | None = field(default=None, repr=False)
    _ai: dict[str, Any] | None = field(default=None, repr=False)

    @property
    def buyers(self) -> dict[str, stats.Buyer]:
        if self._buyers is None:
            self._buyers = stats.purchases(self.db)
        return self._buyers

    @property
    def people(self) -> dict[str, Any]:
        if self._people is None:
            self._people = stats.people(self.db, window=self.window, now=self.now)
        return self._people

    @property
    def businesses(self) -> dict[str, Any]:
        if self._businesses is None:
            self._businesses = stats.businesses(
                self.db, window=self.window, now=self.now
            )
        return self._businesses

    @property
    def ai(self) -> dict[str, Any]:
        if self._ai is None:
            self._ai = stats.ai_cost(self.db, window=self.window, now=self.now)
        return self._ai


# -- the path and the states ---------------------------------------------------


def _funnel(read: _Read) -> list[str]:
    found = stats.funnel(read.db, read.buyers, window=read.window)
    lines = [
        f"### Funnel: the {found['joined']} customers who signed up in the "
        "window, by the furthest step reached",
        "A later step counts the earlier ones as made. No times are kept "
        "here: only how many reached each step. Each: reached it; share of "
        "those who signed up; share of the step before; dropped before it.",
    ]
    lines += [
        f"- {step['label']}: {step['customers']}; "
        f"{_pct(step['of_joined_pct'])}; {_pct(step['of_previous_pct'])}; "
        f"dropped {step['dropped']}"
        for step in found["steps"]
    ]
    return lines


def _statuses(read: _Read) -> list[str]:
    found = stats.statuses(read.db, now=read.now)
    lines = [f"### Customers now by plan state: {found['total']} in all"]
    lines += [
        f"- {row['label']}: {row['customers']} ({_pct(row['share_pct'])})"
        for row in found["rows"]
    ]
    lines += [
        f"- Paid plan ends within 7 days: {found['ending_7']}, of them with a "
        f"card to renew from: {found['ending_7_with_card']}",
        f"- Paid plan ends within 30 days: {found['ending_30']}, of them with "
        f"a card: {found['ending_30_with_card']}",
    ]
    return lines


def _ladder(read: _Read) -> list[str]:
    found = stats.ladder(read.buyers, window=read.window)
    lines = [
        f"### Ladder: everyone who has ever paid, as of the window's end: "
        f"{found['total']}"
    ]
    lines += [
        f"- {row['label']}: {row['customers']} ({_pct(row['share_pct'])}); "
        f"got there in the window: {row['new_in_window']}"
        for row in found["segments"]
    ]
    lines.append(
        f"- Of «{stats.LADDER_LABELS[stats.YELLOW]}»: came up from Start "
        f"{found['yellow_from_start']}, bought Standart straight away "
        f"{found['yellow_direct']}"
    )
    return lines


def _plans_sold(read: _Read) -> list[str]:
    found = stats.plans_sold(
        read.buyers, window=read.window, plans=stats.every_plan(read.db)
    )
    currency = found["currency"]
    lines = [f"### Plans sold in the window: {found['bills']} bills"]
    lines += [
        f"- {row['name']}: {row['buyers']} buyers, {row['bills']} bills "
        f"({_pct(row['share_pct'])} of bills), "
        f"{_money(row['amount_minor'], currency)}; a customer's first bill "
        f"{row['first_time']}, second {row['second_time']}, third or later "
        f"{row['third_or_later']}; the same plan again {row['same_plan_again']}"
        for row in found["rows"]
    ] or ["- nothing sold"]
    lines.append("How many times customers have bought, as of the window's end:")
    lines += [
        f"- {row['label']}: {row['customers']} ({_pct(row['share_pct'])})"
        for row in found["times"]
    ]
    return lines


def _loyal(read: _Read) -> list[str]:
    found = stats.loyal(
        read.buyers,
        window=read.window,
        live=stats.live_owner_ids(read.db, now=read.now),
        plans=stats.every_plan(read.db),
    )
    lines = [
        f"### Loyal (the same plan {found['run']} times in a row), as of the "
        "window's end",
        f"- Customers: {found['customers']} ({_pct(found['share_pct'])} of "
        f"everyone who paid); still on a plan now: {found['still_live']}; "
        f"became loyal in the window: {found['new_in_window']}",
    ]
    lines += [f"- {row['name']}: {row['customers']}" for row in found["plans"]]
    return lines


def _keeping(read: _Read) -> list[str]:
    found = stats.keeping(read.buyers, window=read.window, now=read.now)
    step = found["cohort_step_days"]
    lines = [
        "### Keeping paid customers across the window",
        f"- Paid up at the window's start: {found['paid_at_start']}; at its "
        f"end: {found['paid_at_end']}",
        f"- Lost (paid at the start, not at the end): {found['lost']} "
        f"(churn: {_pct(found['churn_pct'])})",
        f"- Came back after a gap: {found['came_back']}",
        f"Of each month's first-time buyers, still paid up after every {step} days:",
    ]
    for row in found["cohorts"]:
        kept = [
            f"{step * number} days {value}%"
            for number, value in enumerate(row["kept_pct"], start=1)
            if value is not None
        ]
        lines.append(
            f"- {row['label']}: {row['customers']} new buyers"
            + (f"; {', '.join(kept)}" if kept else "; too early to say")
        )
    return lines


def _start(read: _Read) -> list[str]:
    found = stats.start_out(
        stats.start_cohort(read.db, read.buyers, window=read.window, now=read.now)
    )
    median = found["median_days_to_move"]
    lines = [
        "### Start to Standart: customers whose first Start was paid in the window",
        f"- Bought Start: {found['started']}; Start still running: "
        f"{found['in_start']}; Start over or moved on: {found['due']}",
        f"- Moved on to Standart or higher: {found['moved']} "
        f"({_pct(found['moved_pct'])} of those whose Start is over or moved on)",
        "- Median days from the Start payment to the next plan: "
        + ("n/a" if median is None else str(median)),
    ]
    lines += [
        f"- Moved to {row['name']}: {row['customers']}" for row in found["moved_to"]
    ]
    lines.append(f"- Did not move on: {found['lost']}; the first step never made:")
    lines += [
        f"  - {row['label']}: {row['customers']} ({_pct(row['share_pct'])})"
        for row in found["lost_reasons"]
        if row["customers"]
    ]
    return lines


# -- money and growth ----------------------------------------------------------


def _money_block(read: _Read) -> list[str]:
    found = stats.money(read.db, read.buyers, window=read.window, now=read.now)
    currency = found["currency"]
    lines = [
        f"### Money in the window ({currency}; other currencies not summed in)",
        f"- Takings: {_money(found['takings_minor'], currency)} from "
        f"{found['bills']} bills",
    ]
    lines += [
        f"- {row['label']}: {_money(row['amount_minor'], currency)} "
        f"({_pct(row['share_pct'])}), {row['bills']} bills"
        for row in found["kinds"]
    ]
    lines.append("By payment method:")
    lines += [
        f"- {row['label']}: {_money(row['amount_minor'], currency)} "
        f"({_pct(row['share_pct'])}), {row['bills']} bills"
        for row in found["methods"]
    ] or ["- no payments"]
    lines += [
        f"- Customers who paid for a plan: {found['plan_payers']}; plan money "
        f"per such customer: {_money(found['per_payer_minor'], currency)}",
        "- Lifetime plan money per customer who ever paid, as of the window's "
        f"end: {_money(found['lifetime_per_customer_minor'], currency)}",
        f"- Paid from the balance: {_money(found['wallet_minor'], currency)}; "
        f"discounts given: {_money(found['discount_minor'], currency)}",
        f"- Refunds: {found['refunded']}, {_money(found['refunded_minor'], currency)}",
        f"- Paying now: {found['paying_now']}; with a card for autopay: "
        f"{found['autopay_now']} ({_pct(found['autopay_pct'])})",
    ]
    return lines


def _growth(read: _Read) -> list[str]:
    currency = stats.money(read.db, read.buyers, window=read.window, now=read.now)[
        "currency"
    ]
    found = stats.growth(read.db, window=read.window, currency=currency)
    return [
        "### Promo codes and referrals in the window",
        f"- Promo codes used: {found['promo_used']} by "
        f"{found['promo_customers']} customers; discount "
        f"{_money(found['promo_discount_minor'], currency)}; days given "
        f"{found['promo_days']}",
        f"- Came by a referral: {found['referred']}; of them paid: "
        f"{found['referred_paid']} ({_pct(found['referred_paid_pct'])}); "
        f"customers who referred: {found['referrers']}",
        f"- Referral rewards: {found['rewards']}, "
        f"{_money(found['rewards_minor'], currency)}",
    ]


# -- who the customers are -----------------------------------------------------


def _split(title: str, found: dict[str, Any]) -> list[str]:
    lines = [
        f"### Customers by {title}: {found['total']} in all",
        "Each: customers now (share); signed up in the window; ever paid "
        "(share of that row); paying now.",
    ]
    lines += [
        f"- {row['label']}: {row['customers']} ({_pct(row['share_pct'])}); "
        f"in the window {row['joined_in_window']}; ever paid {row['ever_paid']} "
        f"({_pct(row['paid_pct'])}); paying now {row['paying_now']}"
        for row in found["rows"]
    ]
    return lines


def _roles(read: _Read) -> list[str]:
    return _split("role (who they said they are)", read.people["roles"])


def _signup_via(read: _Read) -> list[str]:
    return _split("how they signed up", read.people["signup_via"])


def _languages(read: _Read) -> list[str]:
    return _split("language", read.people["languages"])


def _sources(read: _Read) -> list[str]:
    return _split("the ad source that brought them (UTM)", read.people["utm_sources"])


def _directions(read: _Read) -> list[str]:
    found = read.businesses
    lines = [
        f"### Businesses by direction, now: {found['total']} businesses of "
        f"{found['owners']} customers",
        "A customer may own several businesses. Each: businesses (share); "
        "created in the window; owners; owners paying now (share of owners).",
    ]
    lines += [
        f"- {row['label']}: {row['businesses']} ({_pct(row['share_pct'])}); "
        f"in the window {row['new_in_window']}; owners {row['owners']}; "
        f"paying {row['paying_owners']} ({_pct(row['paying_pct'])})"
        for row in found["directions"]
    ]
    if found["custom_top"]:
        lines.append("Most common among the ones customers wrote themselves:")
        lines += [
            f"- {row['label']}: {row['businesses']} ({_pct(row['share_pct'])})"
            for row in found["custom_top"]
        ]
    return lines


def _cities(read: _Read) -> list[str]:
    found = read.businesses
    lines = [f"### Businesses by city, now: {found['total']} businesses"]
    lines += [
        f"- {row['label']}: {row['businesses']} ({_pct(row['share_pct'])})"
        for row in found["cities"]
    ]
    lines.append(f"- No city given: {found['no_city']}")
    return lines


# -- what is used, what it costs -----------------------------------------------


def _usage(read: _Read) -> list[str]:
    found = stats.usage(read.db, window=read.window, now=read.now)
    per_owner = found["leads_per_owner"]
    lines = [f"### What the {found['paying_now']} customers paying now use"]
    lines += [
        f"- {row['label']}: {row['customers']} ({_pct(row['share_pct'])})"
        for row in found["parts"]
    ]
    lines += [
        "In the window, all customers:",
        f"- Ads launched: {found['launched']} by {found['launchers']} "
        f"customers; launches failed: {found['failed']} "
        f"({_pct(found['failed_pct'])} of attempts)",
        f"- Leads: {found['leads']} to {found['lead_owners']} customers"
        + (f"; {per_owner} per such customer" if per_owner is not None else ""),
    ]
    return lines


def _ai_cost(read: _Read) -> list[str]:
    found = read.ai
    tokens = found["tokens"]
    lines = [
        "### What Claude cost in the window (USD)",
        f"- For customers: {_usd(found['cost_micros'])} over {found['calls']} "
        f"calls by {found['customers']} customers; for staff: "
        f"{_usd(found['staff_cost_micros'])}",
        f"- Per customer a month: {_usd(found['per_customer_month_micros'])}",
        f"- Tokens: input {tokens.get('input', 0)}, output "
        f"{tokens.get('output', 0)}, read from cache "
        f"{tokens.get('cache_read', 0)}, written to cache "
        f"{tokens.get('cache_write', 0)}",
    ]
    lines += _under(
        "By purpose:",
        [
            f"- {row['label']}: {_usd(row['cost_micros'])} "
            f"({_pct(row['share_pct'])}), {row['customers']} customers, "
            f"{row['calls']} calls"
            for row in found["purposes"]
        ],
    )
    lines += _under(
        "By model:",
        [
            f"- {row['label']}: {_usd(row['cost_micros'])} "
            f"({_pct(row['share_pct'])}), {row['calls']} calls"
            for row in found["models"]
        ],
    )
    lines += _under(
        "By the customer's plan now:",
        [
            f"- {row['name']}: {_usd(row['cost_micros'])}, {row['customers']} "
            f"customers, {_usd(row['per_customer_month_micros'])} per customer "
            "a month"
            for row in found["plans"]
        ],
    )
    lines += _under(
        "By month:",
        [
            f"- {row['label']}: {_usd(row['cost_micros'])}, {row['customers']} "
            f"customers, average {_usd(row['average_micros'])}, median "
            f"{_usd(row['median_micros'])}"
            for row in found["months"]
        ],
    )
    return lines


def _ai_top(read: _Read) -> list[str]:
    lines = ["### Customers Claude cost most in the window (USD)"]
    lines += [
        f"- {row['email'] or 'deleted account'}: {_usd(row['cost_micros'])}"
        for row in read.ai["top"]
    ] or ["- nobody"]
    return lines


BLOCKS: dict[str, Callable[[_Read], list[str]]] = {
    "funnel": _funnel,
    "statuses": _statuses,
    "ladder": _ladder,
    "plans_sold": _plans_sold,
    "loyal": _loyal,
    "keeping": _keeping,
    "start": _start,
    "money": _money_block,
    "growth": _growth,
    "roles": _roles,
    "signup_via": _signup_via,
    "languages": _languages,
    "sources": _sources,
    "directions": _directions,
    "cities": _cities,
    "usage": _usage,
    "ai_cost": _ai_cost,
    "ai_top": _ai_top,
}


def statistics(db: Session, *, query: Statistics, now: datetime) -> str:
    window = window_of(query, today=localtime(now).date())
    read = _Read(db=db, window=window, now=now)
    lines = [
        "## Statistika",
        f"Window: {window.start:%d.%m.%Y} - {window.end:%d.%m.%Y} "
        f"({window.days} days, office time). Customers only: no staff.",
    ]
    if window.refused:
        lines.append(f"The days asked for were not read: {window.refused}")
    for part in dict.fromkeys(query.parts):
        lines += ["", *BLOCKS[part](read)]
    return "\n".join(lines)


__all__ = ["BLOCKS", "statistics"]
