"""What a call costs, in whole minor units.

Money never becomes a float, and that rule does not relax because the
amount is small. A month of onboarding calls is thousands of them, and a
rounding error repeated that often is the difference between a bill that
reconciles and one that does not.
"""

from llmkit.models import Pricing

# Illustrative numbers, not a claim about anyone's price list: 30 cents per
# million input tokens, 150 per million output.
PRICES = Pricing(input_per_mtok_minor=3000, output_per_mtok_minor=15000, currency="USD")


def test_a_million_tokens_costs_exactly_the_quoted_price() -> None:
    assert PRICES.cost_minor(input_tokens=1_000_000, output_tokens=0) == 3000


def test_input_and_output_are_priced_separately() -> None:
    """Output costs several times more, which is why they cannot be added."""
    cost = PRICES.cost_minor(input_tokens=1_000_000, output_tokens=1_000_000)

    assert cost == 18000


def test_the_result_is_a_whole_number_of_minor_units() -> None:
    cost = PRICES.cost_minor(input_tokens=1234, output_tokens=567)

    assert isinstance(cost, int)


def test_a_fraction_of_a_unit_rounds_down() -> None:
    """Down, not up: a total that drifts above the real bill costs trust."""
    assert PRICES.cost_minor(input_tokens=1, output_tokens=0) == 0


def test_an_unconfigured_price_records_zero_rather_than_guessing() -> None:
    """Visibly wrong in the admin beats invisibly wrong in a total."""
    assert Pricing().cost_minor(input_tokens=1_000_000, output_tokens=1_000_000) == 0


def test_the_currency_travels_with_the_price() -> None:
    assert PRICES.currency == "USD"


# --- What a cached prompt costs --------------------------------------
#
# Three rates at once, and only one of them is the ordinary input rate.
# Uncounted, the other two would make every bill *look* smaller than it is.
def test_cache_reads_are_charged_and_are_not_input_tokens() -> None:
    """The arithmetic the monthly ceiling depends on.

    A cache read does not appear in ``input_tokens`` - the API counts it
    separately - so a total built from the input rate alone would be a
    total of the tokens that were not cached.
    """
    pricing = Pricing(
        input_per_mtok_minor=300,
        output_per_mtok_minor=1_500,
        cache_read_per_mtok_minor=30,
        currency="USD",
    )

    assert (
        pricing.cost_minor(
            input_tokens=1_000_000, output_tokens=0, cache_read_tokens=1_000_000
        )
        == 330
    )


def test_writing_the_cache_costs_more_than_not_caching() -> None:
    """The premium, which is why caching is a bet rather than a saving.

    A prefix written and never read again costs more than one that was
    never cached, and that is exactly what happens to a prefix under the
    provider's minimum length.
    """
    pricing = Pricing(
        input_per_mtok_minor=300, cache_write_per_mtok_minor=375, currency="USD"
    )

    cached = pricing.cost_minor(
        input_tokens=0, output_tokens=0, cache_write_tokens=1_000_000
    )
    plain = pricing.cost_minor(input_tokens=1_000_000, output_tokens=0)
    assert cached > plain


def test_a_call_that_used_no_cache_costs_exactly_what_it_always_did() -> None:
    pricing = Pricing(
        input_per_mtok_minor=300,
        output_per_mtok_minor=1_500,
        cache_write_per_mtok_minor=375,
        cache_read_per_mtok_minor=30,
        currency="USD",
    )

    assert pricing.cost_minor(input_tokens=1_000_000, output_tokens=1_000_000) == 1_800


# --- The exact figure -------------------------------------------------------


def test_the_exact_cost_keeps_what_whole_units_drop() -> None:
    """Tokens times a price per million is millionths of a minor unit, with
    nothing to round. One input token is three thousand of them here."""
    assert PRICES.cost_micros(input_tokens=1, output_tokens=0) == 3_000
    assert PRICES.cost_micros(input_tokens=1234, output_tokens=567) == (
        1234 * 3000 + 567 * 15000
    )


def test_whole_units_are_the_exact_cost_rounded_down() -> None:
    exact = PRICES.cost_micros(input_tokens=1234, output_tokens=567)

    assert PRICES.cost_minor(input_tokens=1234, output_tokens=567) == exact // 1_000_000


def test_a_logo_look_is_not_free() -> None:
    """The call that showed the problem: about half a cent, recorded as
    nought when only whole cents were kept."""
    rates = Pricing(
        input_per_mtok_minor=200, output_per_mtok_minor=1000, currency="USD"
    )

    assert rates.cost_minor(input_tokens=1781, output_tokens=211) == 0
    assert rates.cost_micros(input_tokens=1781, output_tokens=211) == 567_200


def test_a_result_shows_whole_units_of_its_exact_cost() -> None:
    from llmkit import LLMResult, Spend

    result = LLMResult(
        value=None,
        input_tokens=1,
        output_tokens=1,
        cost_micros=2_567_200,
        currency="USD",
        latency_ms=1,
        prompt_name="p",
        prompt_version="v1",
        model="m",
    )

    assert result.cost_minor == 2
    assert Spend(cost_micros=999_999).cost_minor == 0
