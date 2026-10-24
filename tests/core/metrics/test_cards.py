"""The catalogue of figures a campaign panel may draw.

Small rules, and every one of them is a way of losing somebody's setting
without anything failing.

**A stored key is permanent.** The preference column holds these strings.
A renamed key is a card that silently stops appearing for every account
that had chosen it, and nothing anywhere raises.

**Absent and empty are different answers.** No preference row means the
account has never opened the screen; an empty list means somebody unticked
everything and meant it. Collapsing the two is the settings screen that
puts back what was just removed.

**Order belongs to the catalogue, not to the submission.** What is stored
is a set of choices. If the stored order were honoured, a save from a
browser that reordered the fields would shuffle somebody's screen.
"""

from core.metrics import cards


def test_every_default_is_a_card_the_catalogue_has() -> None:
    """A default naming a key nothing defines is a card nobody can untick."""
    assert set(cards.DEFAULT_KEYS) <= set(cards.BY_KEY)


def test_no_key_is_defined_twice() -> None:
    """Two entries under one key means the second silently wins."""
    assert len(cards.BY_KEY) == len(cards.CARDS)


def test_every_card_belongs_to_a_group_that_is_drawn() -> None:
    """A group missing from ``GROUPS`` is a card no screen ever renders."""
    assert {card.group for card in cards.CARDS} <= set(cards.GROUPS)


def test_no_preference_at_all_means_the_defaults() -> None:
    assert cards.stored_or_default(None) == cards.DEFAULT_KEYS


def test_choosing_nothing_is_honoured_rather_than_reset() -> None:
    """The whole reason the model distinguishes an absent row from an empty one."""
    assert cards.stored_or_default([]) == ()


def test_a_key_the_catalogue_never_heard_of_is_dropped() -> None:
    """What a rolled-back deploy and a hand-edit in the admin both arrive as."""
    assert cards.chosen_keys(["spend", "roas", ""]) == ("spend",)


def test_a_column_holding_something_that_is_not_a_list_draws_nothing() -> None:
    """A JSON column can hold anything. None of it may reach the screen."""
    assert cards.chosen_keys({"spend": True}) == ()
    assert cards.chosen_keys("spend") == ()


def test_a_list_with_something_that_is_not_a_string_in_it_still_works() -> None:
    assert cards.chosen_keys(["spend", 7, None]) == ("spend",)


def test_the_order_is_the_catalogue_s_and_not_the_stored_one() -> None:
    stored = ["spend", "cpl"]
    catalogue = [card.key for card in cards.CARDS]
    chosen = cards.chosen_keys(stored)
    assert list(chosen) == sorted(chosen, key=catalogue.index)
    assert chosen == ("cpl", "spend")


def test_a_withdrawn_figure_somebody_had_ticked_is_dropped() -> None:
    """The quality marking is off and its three figures left the catalogue.

    Every account that had ticked one still has the string in its
    preference column, and this is exactly the case ``chosen_keys`` is
    defensive about: an unknown key is dropped rather than drawn, so the
    withdrawal does not need a migration and the tick comes back with the
    catalogue entry.
    """
    assert cards.chosen_keys(["spend", "cpql", "qualified"]) == ("spend",)


def test_the_list_row_is_the_same_real_cards_everywhere() -> None:
    """Fixed rather than filtered out of the owner's choice, which is what
    makes a column readable down a list: each figure is in the same place
    on every row of every account."""
    assert all(key in cards.BY_KEY for key in cards.ROW_KEYS)
    assert len(set(cards.ROW_KEYS)) == len(cards.ROW_KEYS)


def test_the_row_reads_in_ads_manager_s_order() -> None:
    """Spend, what it brought, what one cost - then whether anybody is
    being reached, so a campaign with no result yet still shows it runs."""
    assert cards.ROW_KEYS == ("spend", "leads", "cpl", "reach", "impressions")


def test_only_the_figures_that_count_people_are_read_from_one_day() -> None:
    """Reach and the unique counts. Anything else on a day basis is a bug.

    A count of events summed over a range is right; a count of people is
    not, and the split is what the two bases exist to keep straight.
    """
    daily = {card.key for card in cards.CARDS if card.basis == "day"}
    assert daily == {"reach", "frequency", "unique_clicks"}


def test_the_costs_all_know_that_lower_is_better() -> None:
    """A panel that coloured a falling cost the same as a falling lead
    count is one that teaches people to ignore the colour."""
    costs = {"cpl", "cpm", "cpc"}
    assert all(cards.BY_KEY[key].lower_is_better for key in costs)


def test_the_figures_a_first_account_sees_are_the_ones_it_can_act_on() -> None:
    """What it cost, what it produced, who saw it and whether anybody clicked.

    ``cpql`` and ``qualified`` were the first two of these and are offered
    nowhere while the marking is withdrawn - a settings screen cannot tick
    a figure the catalogue no longer holds.
    """
    assert cards.DEFAULT_KEYS == (
        "cpl",
        "spend",
        "leads",
        "impressions",
        "reach",
        "ctr",
    )
    assert "cpql" not in cards.BY_KEY


def test_specs_for_looks_up_and_does_not_re_sort() -> None:
    """Ordering is ``chosen_keys``' job, and doing it twice is doing it twice.

    Every caller passes that function's output, which is already in
    catalogue order - so this one keeps what it is handed rather than
    holding a second copy of the rule.
    """
    assert tuple(spec.key for spec in cards.specs_for(("spend", "cpl"))) == (
        "spend",
        "cpl",
    )
