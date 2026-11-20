"""The Central Bank's answer for one day, as the rates we keep."""

from datetime import date
from decimal import Decimal

from app.modules.metrics.services.rates import read_rows


def test_a_rate_is_for_one_unit_on_the_day_the_bank_set_it() -> None:
    rows = read_rows(
        [
            {"Ccy": "USD", "Nominal": "1", "Rate": "12014.37", "Date": "14.11.2026"},
            {"Ccy": "VND", "Nominal": "10", "Rate": "4.67", "Date": "14.11.2026"},
        ]
    )

    assert rows == [
        (date(2026, 11, 14), "USD", Decimal("12014.37")),
        (date(2026, 11, 14), "VND", Decimal("0.467")),
    ]


def test_what_cannot_be_read_is_left_out() -> None:
    rows = read_rows(
        [
            {"Ccy": "USD", "Nominal": "1", "Rate": "abc", "Date": "14.11.2026"},
            {"Ccy": "EUR", "Nominal": "0", "Rate": "13000", "Date": "14.11.2026"},
            {"Ccy": "RUB", "Nominal": "1", "Rate": "146.19", "Date": "yesterday"},
            {"Ccy": "KZT", "Nominal": "1", "Rate": "0", "Date": "14.11.2026"},
            {"Nominal": "1"},
            "text",
        ]
    )

    assert rows == []
    assert read_rows({"error": "down"}) == []
