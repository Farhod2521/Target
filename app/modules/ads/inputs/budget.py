"""The daily budget as typed in major units, held to the provider's floor."""

from decimal import Decimal, InvalidOperation

from app.common.money import MoneyRules, format_minor
from app.modules.ads.inputs import Problems

PRESET_COUNT = 4
ROUND_STEPS = (1, 2, 5)


def budget_minor(
    amount: Decimal | None,
    *,
    currency: str,
    money: MoneyRules,
    floor_minor: int,
    problems: Problems,
    field: str = "daily_budget",
) -> int:
    """The amount in minor units, or ``0`` after adding a problem."""
    places = money.decimal_places(currency)
    if amount is None:
        problems.add(field, "Kunlik byudjetni yozing.")
        return 0
    try:
        step = Decimal(1).scaleb(-places)
        if amount < step or amount != amount.quantize(step):
            raise InvalidOperation
    except InvalidOperation:
        problems.add(field, "Summani to'g'ri yozing.")
        return 0
    given = money.to_minor(amount=amount, currency=currency)
    if floor_minor and given < floor_minor:
        least = format_minor(amount_minor=floor_minor, currency=currency, places=places)
        problems.add(field, f"Kuniga eng kamida {least} bo'lishi kerak.")
        return 0
    return given


def cap_minor(
    amount: Decimal,
    *,
    currency: str,
    money: MoneyRules,
    problems: Problems,
    field: str = "spend_cap",
) -> int:
    """A spend cap in minor units, or ``0`` after adding a problem.

    Zero is allowed - it is the absence of a cap, as Django's
    ``min_value=0`` had it - but not a figure finer than the currency's
    smallest unit, which would otherwise be rounded into something else.
    """
    step = Decimal(1).scaleb(-money.decimal_places(currency))
    try:
        if amount < 0 or amount != amount.quantize(step):
            raise InvalidOperation
    except InvalidOperation:
        problems.add(field, "Summani to'g'ri yozing.")
        return 0
    return int(money.to_minor(amount=amount, currency=currency))


def budget_presets(*, min_daily_minor: int, places: int) -> list[str]:
    """Four round amounts in whole currency, read off the floor."""
    if min_daily_minor <= 0:
        return []
    start = Decimal(min_daily_minor * 2).scaleb(-places)
    amounts: list[Decimal] = []
    decade = Decimal(10) ** start.adjusted()
    while len(amounts) < PRESET_COUNT:
        for step in ROUND_STEPS:
            amount = decade * step
            if amount >= start and len(amounts) < PRESET_COUNT:
                amounts.append(amount)
        decade *= 10
    return [f"{amount.quantize(Decimal(1).scaleb(-places)):f}" for amount in amounts]


__all__ = ["budget_minor", "budget_presets", "cap_minor"]
