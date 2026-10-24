"""Meta's own arithmetic for a currency's smallest unit.

Every amount that crosses into Meta is an integer count of the ad account
currency's smallest unit - ``daily_budget`` going out, ``min_daily_budget``
and ``spend_cap`` coming back. What that integer *means* is Meta's table,
not ISO 4217's, and the two do not agree everywhere.

These tests pin the two decisions that table encodes: that it holds only
what has been read from Meta, and that the currencies this deployment
actually meets are counted the way the product counts them today.
"""

from adskit import ISO_MONEY
from metaads.money import META_CURRENCY_PLACES, META_MONEY


def test_the_table_holds_no_guesses() -> None:
    """Empty is a statement, not an omission.

    An offset written down from memory is the hundredfold error committed
    on purpose. Entries arrive here after being read off a live account,
    and this test is what a future edit has to argue with.
    """
    assert META_CURRENCY_PLACES == {}


def test_meta_counts_the_som_in_hundredths() -> None:
    """UZS is two decimals here, and that is ISO 4217's answer.

    **Unverified against Meta.** The som's sub-unit is not used in daily
    life, so Meta counting it whole would be unsurprising - and would make
    every budget on an UZS account a hundred times what was typed. It is
    pinned rather than assumed quietly: the day the offset is read off a
    live account this test either passes untouched or names exactly what
    has to change beside it.
    """
    assert META_MONEY.decimal_places("UZS") == 2
    assert META_MONEY.to_minor(amount="50000", currency="UZS") == 5_000_000


def test_the_dollar_is_unchanged_by_any_of_this() -> None:
    assert META_MONEY.decimal_places("USD") == 2
    assert META_MONEY.to_minor(amount="12.34", currency="USD") == 1234


def test_a_currency_with_no_sub_unit_is_still_counted_whole() -> None:
    """The standard's zero-decimal list is inherited, not restated."""
    assert META_MONEY.decimal_places("JPY") == 0
    assert META_MONEY.to_minor(amount="1000", currency="JPY") == 1000


def test_meta_agrees_with_the_standard_everywhere_it_has_not_said_otherwise() -> None:
    """Today the two tables are identical, which is the safe starting state.

    Written as a comparison rather than as a list of codes so that adding
    one verified override makes this fail loudly at the currency it was
    added for, instead of passing because nobody updated the list.
    """
    for code in ("USD", "EUR", "UZS", "JPY", "KRW", "RUB", "KZT", "TRY"):
        assert META_MONEY.decimal_places(code) == ISO_MONEY.decimal_places(code)


def test_the_registered_bundle_carries_the_table() -> None:
    """A table nothing reaches is a table that protects nothing."""
    from metaads.adapter import bundle

    assert bundle().money is META_MONEY
