"""Advertising set against its sales: every answer, and every reason for none."""

from decimal import Decimal

from core.metrics.sales import (
    SALES,
    SALES_KEYS,
    SalesFigures,
    answers,
    completeness,
)


def figures(**given: object) -> SalesFigures:
    base: dict[str, object] = {
        # 1 200 000,00 so'm spent, 40 leads, 10 qualified, 4 sold for 6 mln.
        "spend_minor": 120_000_000,
        "leads": 40,
        "taken": 30,
        "judged": 28,
        "qualified": 10,
        "won": 4,
        "lost": 12,
        "junk": 6,
        "revenue_minor": 600_000_000,
        "waits": [5.0, 15.0, 240.0],
        "deals": [60.0, 1440.0, 2880.0, 10_000.0],
    }
    return SalesFigures(**(base | given))  # type: ignore[arg-type]


def test_every_metric_has_an_answer_and_words() -> None:
    found = answers(figures())

    assert set(found) == set(SALES_KEYS)
    assert all(metric.label and metric.hint for metric in SALES)


def test_the_six_figures_the_owner_asked_for() -> None:
    found = answers(figures())

    assert found["spend"].value == 120_000_000
    assert found["revenue"].value == 600_000_000
    # 6 000 000 / 1 200 000.
    assert found["roas"].value == Decimal("5.00")
    # 1 200 000 / 4 customers.
    assert found["cac"].value == 30_000_000
    # 4 of 40 leads.
    assert found["conversion"].value == Decimal("10.00")
    # The middle of four deals: between one and two days.
    assert found["deal_time"].value == 2160


def test_the_figures_around_them() -> None:
    found = answers(figures())

    assert found["cpl"].value == 3_000_000
    assert found["cpql"].value == 12_000_000
    assert found["qualified_share"].value == Decimal("25.00")
    assert found["close_rate"].value == Decimal("40.00")
    assert found["avg_deal"].value == 150_000_000
    assert found["first_response"].value == 15
    assert (found["leads"].value, found["qualified"].value, found["sales"].value) == (
        40,
        10,
        4,
    )


def test_with_the_crm_off_nothing_is_nought() -> None:
    found = answers(figures(crm=False))

    assert {answer.missing for answer in found.values()} == {"no_crm"}
    assert completeness(figures(crm=False)).level == "off"


def test_no_sale_closed_is_unknown_revenue_not_nought() -> None:
    found = answers(figures(won=0, revenue_minor=0, deals=[]))

    for key in ("revenue", "roas", "cac", "avg_deal", "deal_time"):
        assert (found[key].value, found[key].missing) == (None, "no_sales")
    # What does not need a sale is still told.
    assert found["conversion"].value == Decimal("0.00")
    assert found["cpl"].value == 3_000_000
    assert found["spend"].value == 120_000_000


def test_nothing_spent_prices_nothing() -> None:
    found = answers(figures(spend_minor=0))

    assert found["spend"].value == 0
    for key in ("roas", "cac", "cpl", "cpql"):
        assert (found[key].value, found[key].missing) == (None, "no_spend")
    assert found["revenue"].value == 600_000_000


def test_a_manager_has_no_spend_of_his_own() -> None:
    found = answers(figures(spend_minor=None))

    for key in ("spend", "roas", "cac", "cpl", "cpql"):
        assert found[key].missing == "not_here"
    assert found["revenue"].value == 600_000_000
    assert found["conversion"].value == Decimal("10.00")


def test_no_leads_divides_nothing() -> None:
    found = answers(SalesFigures(spend_minor=5_000))

    assert found["cpl"].missing == "no_base"
    assert found["conversion"].missing == "no_base"
    assert found["revenue"].missing == "no_base"
    assert found["first_response"].missing == "no_base"
    assert completeness(SalesFigures()).level == "empty"


def test_spend_with_a_hole_in_it_prices_nothing() -> None:
    # Ten days of thirty unpriced: the sum is two thirds of the truth, and a
    # ROAS from it would look a half better than it is.
    for gap in ("no_rate", "not_kept"):
        found = answers(figures(spend_gap=gap, spend_unpriced_days=10))

        for key in ("spend", "roas", "cac", "cpl", "cpql"):
            assert (found[key].value, found[key].missing) == (None, gap)
        # What needs no spend is still told.
        assert found["revenue"].value == 600_000_000
        assert found["conversion"].value == Decimal("10.00")


def test_revenue_with_a_sale_missing_is_not_told_as_if_whole() -> None:
    found = answers(figures(unpriced=1, revenue_minor=450_000_000))

    assert (found["revenue"].value, found["revenue"].missing) == (None, "no_rate")
    assert (found["roas"].value, found["roas"].missing) == (None, "no_rate")
    # The price of a customer needs only the count of sales.
    assert found["cac"].value == 30_000_000


def test_the_words_do_not_name_a_currency() -> None:
    assert all("so'm" not in metric.hint for metric in SALES)


def test_a_sale_no_rate_priced_is_not_in_the_average() -> None:
    # Four sold, one written in a currency no rate prices: three are priced.
    found = answers(figures(unpriced=1, revenue_minor=450_000_000))

    assert found["avg_deal"].value == 150_000_000
    assert found["sales"].value == 4


def test_completeness_says_how_far_the_leads_are_worked() -> None:
    worked = completeness(figures())

    assert (worked.level, worked.handled_pct, worked.closed_pct, worked.open) == (
        "ok",
        70,
        55,
        18,
    )
    assert "18 ta lid" in worked.note


def test_under_half_looked_at_the_sales_figures_are_called_incomplete() -> None:
    backlog = completeness(figures(judged=10, won=1, lost=2, junk=0))

    assert (backlog.level, backlog.handled_pct) == ("low", 25)
    assert "30 ta lid hali ko'rib chiqilmagan" in backlog.note


def test_everything_closed_needs_no_note() -> None:
    done = completeness(figures(judged=40, won=4, lost=30, junk=6))

    assert (done.level, done.closed_pct, done.open, done.note) == ("ok", 100, 0, "")
