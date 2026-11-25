"""What a plan costs this account, in so'm.

Bills are always in so'm: Rahmat takes nothing else and the money lands in
so'm. An account in Uzbekistan pays the plan's so'm prices. An account
elsewhere pays its dollar prices, turned into so'm at the Central Bank's
rate of the day (rounded up to the whole so'm), and the rate is kept on the
bill, so that the bill reads back as the same dollars later. A plan with no
dollar price set charges its so'm price abroad too.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Final

from app.common.money import to_minor
from app.modules.accounts.models import User
from app.modules.billing.models import Plan
from app.modules.billing.selectors.display import (
    ABROAD_CURRENCY,
    HOME_CURRENCY,
    Display,
    usd_rate,
)

HOME: Final = "UZ"


def abroad(owner: User | None) -> bool:
    """Whether the account pays the dollar prices; an unknown country is home."""
    return owner is not None and (owner.country or HOME) != HOME


@dataclass(frozen=True, slots=True)
class PriceBook:
    """``rate``: so'm per dollar when the dollar prices apply, else None."""

    rate: Decimal | None = None
    rate_date: str = ""

    @property
    def in_dollars(self) -> bool:
        return self.rate is not None

    @property
    def kept_rate(self) -> str:
        """The rate as the bill keeps it; "" for so'm prices."""
        return str(self.rate) if self.rate is not None else ""

    def _som(self, som: int, cents: int) -> int:
        if self.rate is None or cents <= 0:
            return som
        value = Decimal(cents) * self.rate / 100
        return int(value.to_integral_value(rounding=ROUND_CEILING))

    def plan_som(self, plan: Plan) -> int:
        return self._som(plan.price, plan.price_usd_cents)

    def page_som(self, plan: Plan) -> int:
        return self._som(plan.extra_page_price, plan.extra_page_price_usd_cents)

    def seat_som(self, plan: Plan) -> int:
        return self._som(plan.crm_seat_price, plan.crm_seat_price_usd_cents)

    def plan_minor(self, plan: Plan) -> int:
        return int(to_minor(amount=str(self.plan_som(plan)), currency=plan.currency))

    def page_minor(self, plan: Plan) -> int:
        return int(to_minor(amount=str(self.page_som(plan)), currency=plan.currency))

    def seat_minor(self, plan: Plan) -> int:
        return int(to_minor(amount=str(self.seat_som(plan)), currency=plan.currency))


HOME_BOOK: Final = PriceBook()


def price_book(owner: User | None, *, kept_rate: str = "") -> PriceBook:
    """The prices ``owner`` pays. ``kept_rate``: a bill's own rate, so that a
    bill priced again keeps its dollars whatever the rate does since."""
    if kept_rate:
        try:
            return PriceBook(rate=Decimal(kept_rate))
        except InvalidOperation:
            pass
    if not abroad(owner):
        return HOME_BOOK
    found = usd_rate()
    if found is None or found[0] <= 0:
        return HOME_BOOK
    return PriceBook(rate=found[0], rate_date=found[1])


def account_display(owner: User) -> Display:
    """How a signed-in account is shown prices: by its own country, not by
    the address it reads from - so'm at home, dollars elsewhere."""
    country = owner.country or HOME
    book = price_book(owner)
    if not book.in_dollars:
        return Display(country=country, currency=HOME_CURRENCY)
    return Display(
        country=country,
        currency=ABROAD_CURRENCY,
        uzs_per_usd=book.rate,
        rate_date=book.rate_date,
    )


def display_book(display: Display | None) -> PriceBook:
    """The prices a display stands for: the dollar ones at its rate abroad."""
    if (
        display is None
        or display.currency != ABROAD_CURRENCY
        or display.uzs_per_usd is None
    ):
        return HOME_BOOK
    return PriceBook(rate=display.uzs_per_usd, rate_date=display.rate_date)
