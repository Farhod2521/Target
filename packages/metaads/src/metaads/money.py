"""How Meta counts the smallest unit of a currency."""

from typing import Final

from adskit.money import MoneyRules

META_CURRENCY_PLACES: Final[dict[str, int]] = {}

META_MONEY: Final = MoneyRules(overrides=META_CURRENCY_PLACES)

__all__ = ["META_CURRENCY_PLACES", "META_MONEY"]
