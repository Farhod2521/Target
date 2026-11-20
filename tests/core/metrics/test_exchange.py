"""Money of one currency read in another at a day's rate."""

from datetime import date
from decimal import Decimal

from core.metrics.exchange import Rates

FRI, SAT, MON = date(2026, 11, 13), date(2026, 11, 14), date(2026, 11, 16)
RATES = Rates(
    [
        ("USD", FRI, Decimal("12000")),
        ("USD", MON, Decimal("12500")),
        ("RUB", FRI, Decimal("150")),
        ("JPY", FRI, Decimal("75")),
    ]
)


def test_the_same_currency_needs_no_rate() -> None:
    assert (
        Rates([]).convert(amount_minor=777, source="EUR", target="eur", day=FRI) == 777
    )


def test_dollars_become_som_at_the_days_rate() -> None:
    # $150.00 at 12 000 is 1 800 000,00 so'm.
    assert (
        RATES.convert(amount_minor=15000, source="USD", target="UZS", day=FRI)
        == 180_000_000
    )


def test_a_day_off_reads_the_rate_set_before_it() -> None:
    assert RATES.rate("USD", SAT) == Decimal("12000")
    assert RATES.rate("USD", MON) == Decimal("12500")
    assert RATES.rate("USD", date(2026, 11, 26)) == Decimal("12500")


def test_a_rate_too_old_to_stand_for_the_day_is_no_rate() -> None:
    # Ten days is the longest the bank leaves a rate standing; past that the
    # rates have stopped being read, and last month's is not this day's.
    assert RATES.rate("USD", date(2026, 11, 27)) is None
    assert (
        RATES.convert(
            amount_minor=100, source="USD", target="UZS", day=date(2027, 1, 1)
        )
        is None
    )


def test_more_currencies_are_added_as_they_turn_up() -> None:
    rates = Rates([("USD", FRI, Decimal("12000"))])
    assert rates.holds("USD") and rates.holds("UZS") and not rates.holds("TRY")

    rates.extend([("TRY", FRI, Decimal("300"))])

    assert rates.holds("TRY")
    assert (
        rates.convert(amount_minor=1000, source="USD", target="TRY", day=FRI) == 40_000
    )


def test_a_day_before_the_first_rate_has_no_answer() -> None:
    assert RATES.rate("USD", date(2026, 11, 12)) is None
    assert (
        RATES.convert(
            amount_minor=100, source="USD", target="UZS", day=date(2026, 11, 12)
        )
        is None
    )


def test_a_currency_without_rates_has_no_answer() -> None:
    assert RATES.convert(amount_minor=100, source="KZT", target="UZS", day=FRI) is None
    assert RATES.convert(amount_minor=100, source="UZS", target="KZT", day=FRI) is None


def test_two_foreign_currencies_cross_through_som() -> None:
    # $10.00 = 120 000 so'm = 800 roubles.
    assert (
        RATES.convert(amount_minor=1000, source="USD", target="RUB", day=FRI) == 80_000
    )


def test_som_becomes_dollars_rounded_half_up() -> None:
    # 100 000,00 so'm / 12 000 = 8.3333 dollars.
    assert (
        RATES.convert(amount_minor=10_000_000, source="UZS", target="USD", day=FRI)
        == 833
    )


def test_a_currency_without_cents_keeps_its_own_units() -> None:
    # 1 500,00 so'm / 75 = 20 yen, and yen has no hundredths.
    assert (
        RATES.convert(amount_minor=150_000, source="UZS", target="JPY", day=FRI) == 20
    )
    assert (
        RATES.convert(amount_minor=20, source="JPY", target="UZS", day=FRI) == 150_000
    )
