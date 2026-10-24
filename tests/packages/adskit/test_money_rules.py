"""How many of a currency's smallest unit make one of it - and whose answer.

The number this decides is the number that gets spent. A budget typed as
"50" leaves this module as an integer, and whether that integer is 50 or
5000 is the difference between a campaign that runs and one that spends a
hundred times what somebody meant.

No database, no Django, no network.
"""

from decimal import Decimal

from adskit import ISO_MONEY, MoneyRules


def test_the_standard_is_what_an_unconfigured_provider_uses() -> None:
    """No overrides means ISO 4217, which is right for all but a handful."""
    assert ISO_MONEY.decimal_places("USD") == 2
    assert ISO_MONEY.decimal_places("JPY") == 0


def test_a_currency_the_provider_said_nothing_about_falls_through() -> None:
    """One override does not replace the table, it patches one row of it."""
    rules = MoneyRules(overrides={"HUF": 0})

    assert rules.decimal_places("USD") == 2
    assert rules.decimal_places("HUF") == 0


def test_the_provider_may_disagree_with_the_standard_in_either_direction() -> None:
    """Not only "provider says fewer".

    A table that could only remove decimals would be a special case dressed
    up as a rule, and the next provider is not obliged to disagree in the
    convenient direction.
    """
    fewer = MoneyRules(overrides={"UZS": 0})
    more = MoneyRules(overrides={"JPY": 2})

    assert fewer.decimal_places("UZS") == 0
    assert more.decimal_places("JPY") == 2


def test_the_code_is_matched_however_it_was_written() -> None:
    """Currency codes arrive from a provider and from a form, in both cases."""
    rules = MoneyRules(overrides={"HUF": 0})

    assert rules.decimal_places("huf") == 0


def test_conversion_follows_the_provider_and_not_the_standard() -> None:
    """The whole point: the same typed number, two integers, one provider.

    ``"1000"`` in a currency the provider counts whole is a thousand. The
    same string under the standard's two decimals is a hundred thousand,
    and both are legal numbers the platform would accept without a word.
    """
    whole = MoneyRules(overrides={"UZS": 0})

    assert whole.to_minor(amount="1000", currency="UZS") == 1000
    assert ISO_MONEY.to_minor(amount="1000", currency="UZS") == 100_000


def test_a_fraction_is_rounded_half_up_rather_than_dropped() -> None:
    """Same rule as the module-level conversion, because it is the same money."""
    assert ISO_MONEY.to_minor(amount=Decimal("12.345"), currency="USD") == 1235


def test_a_zero_decimal_currency_survives_conversion_unmultiplied() -> None:
    assert ISO_MONEY.to_minor(amount="1000", currency="JPY") == 1000


def test_the_rules_are_a_value_and_two_of_the_same_shape_are_equal() -> None:
    """Carried on the provider bundle, compared in tests, never mutated."""
    assert MoneyRules(overrides={"HUF": 0}) == MoneyRules(overrides={"HUF": 0})
