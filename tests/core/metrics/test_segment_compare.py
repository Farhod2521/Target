"""Ranking the slices of an audience without ranking noise.

Three failures this file exists to prevent, in the order they would happen.

**One lead at half the price is not a discovery.** It is one lead. A ranking
that puts a single-lead cell at the top is the classic way an ad set gets
narrowed onto an audience that never did anything.

**The most expensive segment cannot be ranked by cost.** A slice that spent
money and produced nothing has no cost per lead to sort on - dividing by
zero is not "expensive", it is undefined - so it needs its own answer or it
disappears from the report entirely.

**Spending nothing and spending a lot for nothing are not the same failure,
and neither is spending a lot for a little.** Three ways to fall short of the
floor, and lumping them together is how a placement earning eight leads gets
switched off beside one that earned none.

**The average has to include the slices that did badly.** A base computed
only from the segments that survived a floor is a base every one of them
beats, which turns a comparison into a compliment.

No Django, no database, no clock: figures in, verdicts out.
"""

from adskit import MinorUnits

from core.metrics import (
    MIN_SEGMENT_LEADS,
    SegmentFigures,
    compare_segments,
)


def slice_of(
    segment: str, *, spend: int, leads: int, impressions: int = 1000, clicks: int = 40
) -> SegmentFigures:
    return SegmentFigures(
        segment=segment,
        spend_minor=MinorUnits(spend),
        impressions=impressions,
        clicks=clicks,
        leads_reported=leads,
    )


# --- The ranking ----------------------------------------------------------
class TestRanking:
    def test_the_cheapest_slice_comes_first(self) -> None:
        result = compare_segments(
            [
                slice_of("25-34|female", spend=10_000, leads=20),
                slice_of("35-44|male", spend=30_000, leads=20),
            ]
        )

        assert [cost.segment for cost in result.ranked] == [
            "25-34|female",
            "35-44|male",
        ]
        assert result.cheapest is not None
        assert result.cheapest.cpl_reported_minor == 500

    def test_the_index_is_against_the_cuts_own_average(self) -> None:
        """A hundred is the average, fifty is half of it. The form a rule can
        be written in once, in any currency and any month."""
        result = compare_segments(
            [
                slice_of("25-34|female", spend=10_000, leads=20),
                slice_of("35-44|male", spend=30_000, leads=20),
            ]
        )

        assert result.average_cpl_minor == 1000
        assert [cost.cpl_index for cost in result.ranked] == [50, 150]

    def test_the_average_counts_the_slices_that_were_too_small_to_rank(self) -> None:
        """Otherwise the base is computed from the winners and every winner
        beats it."""
        result = compare_segments(
            [
                slice_of("25-34|female", spend=10_000, leads=20),
                slice_of("55-64|male", spend=10_000, leads=1),
            ]
        )

        assert result.average_cpl_minor == round(20_000 / 21)

    def test_the_worst_comparable_slice_is_named_too(self) -> None:
        result = compare_segments(
            [
                slice_of("25-34|female", spend=10_000, leads=20),
                slice_of("35-44|male", spend=30_000, leads=20),
            ]
        )

        assert result.dearest is not None
        assert result.dearest.segment == "35-44|male"


# --- The floor ------------------------------------------------------------
class TestTheFloor:
    def test_a_single_lead_is_never_the_cheapest_segment(self) -> None:
        """The whole reason there is a floor at all."""
        result = compare_segments(
            [
                slice_of("13-17|female", spend=100, leads=1),
                slice_of("25-34|female", spend=20_000, leads=20),
            ]
        )

        assert result.cheapest is not None
        assert result.cheapest.segment == "25-34|female"

    def test_the_slices_below_the_floor_are_kept_and_not_dropped(self) -> None:
        """A cut of twenty-one cells must not report as a cut of three."""
        result = compare_segments(
            [
                slice_of("13-17|female", spend=100, leads=1),
                slice_of("25-34|female", spend=20_000, leads=20),
            ]
        )

        assert [cost.segment for cost in result.thin] == ["13-17|female"]

    def test_a_small_slice_still_carries_its_own_cost(self) -> None:
        """It is not ranked. It is not unknown either - a screen may show it
        with the count beside it, which is what makes it readable."""
        result = compare_segments([slice_of("13-17|female", spend=900, leads=3)])

        assert result.thin[0].cpl_reported_minor == 300
        assert result.thin[0].leads_reported == 3

    def test_the_floor_a_verdict_rests_on_is_carried_with_the_verdict(self) -> None:
        """So a caller that needs a stricter one can say so, and a screen can
        explain why a cell is not in the ranking."""
        result = compare_segments([slice_of("25-34|female", spend=100, leads=1)])

        assert result.min_leads == MIN_SEGMENT_LEADS

    def test_the_caller_may_ask_for_a_stricter_floor(self) -> None:
        result = compare_segments(
            [slice_of("25-34|female", spend=10_000, leads=12)], min_leads=20
        )

        assert result.ranked == ()
        assert [cost.segment for cost in result.thin] == ["25-34|female"]


# --- Spend with nothing to show for it ------------------------------------
class TestBarrenSlices:
    def test_a_slice_that_spent_enough_and_produced_nothing_is_reported(self) -> None:
        """The most expensive segment there is, and a ranking by cost per
        lead cannot contain it."""
        result = compare_segments(
            [
                slice_of("25-34|female", spend=10_000, leads=20),
                slice_of("55-64|male", spend=9_000, leads=0),
            ]
        )

        assert [cost.segment for cost in result.barren] == ["55-64|male"]
        assert result.barren[0].cpl_reported_minor is None

    def test_the_test_is_the_cuts_own_rate_and_not_a_fixed_amount(self) -> None:
        """ "Enough money" means what this cut paid for ten leads. No currency
        and no threshold anybody has to keep up to date."""
        # The cut's average is 500 per lead, so the bar is 5_000.
        rows = [slice_of("25-34|female", spend=10_000, leads=20)]

        cheap = compare_segments([*rows, slice_of("55-64|male", spend=4_999, leads=0)])
        dear = compare_segments([*rows, slice_of("55-64|male", spend=5_000, leads=0)])

        assert cheap.barren == ()
        assert [cost.segment for cost in dear.barren] == ["55-64|male"]

    def test_the_biggest_waster_is_named_first(self) -> None:
        """Sorted by what it cost, because that is the order the money went
        out in - there is no cost per lead to sort these on."""
        result = compare_segments(
            [
                slice_of("25-34|female", spend=10_000, leads=20),
                slice_of("55-64|male", spend=6_000, leads=0),
                slice_of("65+|female", spend=20_000, leads=0),
            ]
        )

        assert [cost.segment for cost in result.barren] == ["65+|female", "55-64|male"]


# --- Nothing to say -------------------------------------------------------
class TestNoAnswer:
    def test_a_cut_with_no_leads_at_all_ranks_nothing(self) -> None:
        """There is nothing to be cheaper *than*. Not a zero average - an
        absent one, and every verdict absent with it."""
        result = compare_segments(
            [
                slice_of("25-34|female", spend=10_000, leads=0),
                slice_of("35-44|male", spend=8_000, leads=0),
            ]
        )

        assert result.average_cpl_minor is None
        assert result.ranked == ()
        assert result.barren == ()
        assert len(result.thin) == 2

    def test_an_empty_cut_is_an_empty_answer(self) -> None:
        result = compare_segments([])

        assert result.cheapest is None
        assert result.dearest is None
        assert result.average_cpl_minor is None

    def test_every_slice_handed_in_comes_back_somewhere(self) -> None:
        """Four lists, one cut, nothing quietly lost between them - and one
        slice of each kind, so the count cannot pass by accident."""
        rows = [
            slice_of("25-34|female", spend=10_000, leads=20),
            slice_of("55-64|male", spend=9_000, leads=0),
            slice_of("45-54|male", spend=9_000, leads=4),
            slice_of("13-17|female", spend=100, leads=1),
        ]

        result = compare_segments(rows)

        assert (len(result.ranked), len(result.barren)) == (1, 1)
        assert (len(result.weak), len(result.thin)) == (1, 1)


# --- What this comparison is not ------------------------------------------
def test_the_basis_is_the_providers_own_lead_count_and_says_so() -> None:
    """Our leads carry no age, so a per-segment cost can only ever rest on
    what the platform reported. There is deliberately no cost per qualified
    lead here: quality is a verdict about a lead we hold, and we cannot say
    which slice it came from."""
    cost = compare_segments([slice_of("25-34|female", spend=10_000, leads=20)]).ranked[
        0
    ]

    assert hasattr(cost, "cpl_reported_minor")
    assert not any("qualified" in name or "cpql" in name for name in vars(type(cost)))


# --- Waste, noise, and the thing between them -----------------------------
# One earning slice runs through every case below: 95 000 for 190 leads, five
# hundred a lead. It is deliberately large, because the bar is computed from
# every slice that earned anything - a small baseline would move underneath
# each case as the case adds its own leads to it.
EARNING = slice_of("facebook|feed", spend=95_000, leads=190)


class TestWasteAgainstNoise:
    def test_money_in_and_nothing_out_is_barren(self) -> None:
        """The list an exclusion is decided from. Its cost per lead is not
        infinite, it is undefined - there was nothing to divide by."""
        result = compare_segments(
            [EARNING, slice_of("audience_network|an_classic", spend=9_000, leads=0)]
        )

        assert [cost.segment for cost in result.barren] == [
            "audience_network|an_classic"
        ]
        assert result.barren[0].cpl_reported_minor is None
        assert result.weak == ()

    def test_money_in_and_a_little_out_is_weak_and_not_barren(self) -> None:
        """It converts, badly. Calling it waste is how a placement earning
        four leads gets switched off beside one earning none."""
        result = compare_segments(
            [EARNING, slice_of("instagram|story", spend=9_000, leads=4)]
        )

        assert result.barren == ()
        assert [cost.segment for cost in result.weak] == ["instagram|story"]

    def test_a_weak_slice_keeps_the_cost_per_lead_a_barren_one_cannot_have(
        self,
    ) -> None:
        """The whole reason the two are separate lists: one of them has a
        price and the other has no such thing."""
        result = compare_segments(
            [
                EARNING,
                slice_of("instagram|story", spend=9_000, leads=4),
                slice_of("audience_network|an_classic", spend=9_000, leads=0),
            ]
        )

        assert result.weak[0].cpl_reported_minor == 2_250
        assert result.weak[0].cpl_index is not None
        assert result.barren[0].cpl_index is None

    def test_a_slice_that_never_had_the_money_is_noise_whatever_it_did(self) -> None:
        """Below the bar there is nothing to say, and saying it anyway is how
        a cheap placement gets a verdict out of four hundred units of spend."""
        result = compare_segments(
            [
                EARNING,
                slice_of("audience_network|rewarded_video", spend=400, leads=0),
                slice_of("messenger|messenger_home", spend=400, leads=1),
            ]
        )

        assert result.barren == ()
        assert result.weak == ()
        assert len(result.thin) == 2

    def test_the_bar_is_the_same_one_for_both_verdicts(self) -> None:
        """The cut earns at five hundred a lead, so ten leads' worth is five
        thousand. One unit either side of it and the slice moves between
        noise and waste; nothing else decides it."""
        under = compare_segments([EARNING, slice_of("x|y", spend=4_999, leads=0)])
        over = compare_segments([EARNING, slice_of("x|y", spend=5_000, leads=0)])

        assert [cost.segment for cost in under.thin] == ["x|y"]
        assert [cost.segment for cost in over.barren] == ["x|y"]

    def test_the_biggest_spender_is_named_first_in_each_list(self) -> None:
        """No cost per lead to sort either list on, so both go by what they
        cost - the order the money went out in."""
        result = compare_segments(
            [
                EARNING,
                slice_of("audience_network|an_classic", spend=20_000, leads=0),
                slice_of("facebook|story", spend=8_000, leads=0),
                slice_of("instagram|reels", spend=30_000, leads=5),
                slice_of("instagram|story", spend=9_000, leads=3),
            ]
        )

        assert [cost.segment for cost in result.barren] == [
            "audience_network|an_classic",
            "facebook|story",
        ]
        assert [cost.segment for cost in result.weak] == [
            "instagram|reels",
            "instagram|story",
        ]


# --- How much was at stake ------------------------------------------------
class TestSpendShare:
    def test_each_slice_says_what_fraction_of_the_money_it_took(self) -> None:
        """What turns "this placement produced nothing" into a decision. At
        two percent it is not worth an edit that restarts a learning phase."""
        result = compare_segments(
            [
                slice_of("facebook|feed", spend=6_000, leads=20),
                slice_of("audience_network|an_classic", spend=4_000, leads=0),
            ]
        )

        assert result.ranked[0].spend_share == 60
        assert result.barren[0].spend_share == 40

    def test_the_share_is_of_the_cut_and_not_of_the_slices_that_did_well(
        self,
    ) -> None:
        """Every slice handed in is in the denominator, including the ones
        nothing can be said about - or a wasteful slice's share would shrink
        as the waste around it grew."""
        result = compare_segments(
            [
                slice_of("facebook|feed", spend=5_000, leads=20),
                slice_of("instagram|story", spend=5_000, leads=0),
                slice_of("audience_network|an_classic", spend=10_000, leads=0),
            ]
        )

        everything = (*result.ranked, *result.barren, *result.weak, *result.thin)
        assert sum(cost.spend_share for cost in everything) == 100

    def test_a_cut_that_spent_nothing_divides_by_nothing(self) -> None:
        result = compare_segments([slice_of("facebook|feed", spend=0, leads=0)])

        assert result.thin[0].spend_share == 0


# --- Leads with nothing spent behind them --------------------------------
def test_a_slice_with_leads_and_no_spend_has_no_cost_rather_than_a_free_one() -> None:
    """The same guard the headline figure has.

    A cut is read off two sources - spend from the provider's insights and
    leads from this product's own table - and the day they disagree is the
    day a slice carries leads with no spend beside them. Divided, that is
    nought; printed, it is the cheapest slice in the report.
    """
    comparison = compare_segments(
        [
            slice_of("18-24", spend=0, leads=MIN_SEGMENT_LEADS + 5),
            slice_of("25-34", spend=200_000, leads=MIN_SEGMENT_LEADS + 5),
        ]
    )

    by_segment = {cost.segment: cost for cost in comparison.ranked}
    assert by_segment["18-24"].cpl_reported_minor is None
    assert by_segment["25-34"].cpl_reported_minor is not None


def test_a_cut_that_spent_nothing_anywhere_is_not_compared_against_nought() -> None:
    """The average is the base every index divides by. Nought there would
    take the whole comparison down with it - and a base of nought divides
    into an index of nought, which reads as "free" against every slice."""
    comparison = compare_segments(
        [
            slice_of("Instagram", spend=0, leads=MIN_SEGMENT_LEADS),
            slice_of("Facebook", spend=0, leads=MIN_SEGMENT_LEADS),
        ]
    )

    assert comparison.average_cpl_minor is None
    assert all(cost.cpl_index is None for cost in comparison.ranked)
