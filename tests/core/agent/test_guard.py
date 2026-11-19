"""The half-hourly guard's rules: what warns, what stops, and what stays quiet."""

from dataclasses import replace

from core.agent.guard import (
    AdToday,
    GroupToday,
    Usual,
    causes,
    eased,
    judge,
    price_step,
    price_times,
)

# One result usually costs 100; a thousand showings 200; the click rate 1 %.
USUAL = Usual(cost_minor=100, link_ctr_bp=100, cpm_minor=200, source="own")


def _group(**changes: object) -> GroupToday:
    """A day-old group launched from here, with nothing yet to say."""
    base = GroupToday(
        adset_id="g1",
        ours=True,
        hours_running=48,
        own_budget=True,
        usual=USUAL,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def _one(group: GroupToday):
    (found,) = judge(group)
    return found


# -- the price ---------------------------------------------------------------------------


def test_price_in_usual_prices() -> None:
    assert price_times(_group(spend_minor=640, results=2)) == 320
    assert price_times(_group(spend_minor=640, results=0)) == 0
    assert price_times(_group(spend_minor=640, results=2, usual=Usual())) == 0


def test_steps() -> None:
    assert [price_step(t) for t in (299, 300, 499, 500, 999, 1_000)] == [
        0, 0, 0, 5, 5, 10,
    ]  # fmt: skip


def test_under_five_usual_prices_nothing_is_said() -> None:
    assert judge(_group(spend_minor=299, results=1)) == []
    assert judge(_group(spend_minor=960, results=3)) == []
    assert judge(_group(spend_minor=1_230, results=3)) == []
    assert judge(_group(spend_minor=1_490, results=3)) == []


def test_three_and_four_with_bad_rates_say_nothing_either() -> None:
    # CPM 320 against 200, CTR 0.4 % against 1 %, at 3.2 usual prices.
    assert judge(_group(spend_minor=960, results=3, impressions=3_000, link_clicks=12)) == []


def test_five_is_the_first_warning() -> None:
    found = _one(_group(spend_minor=1_500, results=3))
    assert (found.kind, found.action, found.step, found.times) == (
        "price", "warn", 5, 500,
    )  # fmt: skip
    assert found.advice == "pause"
    # Still a warning just under ten.
    assert _one(_group(spend_minor=2_990, results=3)).action == "warn"


def test_ten_stops_what_was_launched_here() -> None:
    found = _one(_group(spend_minor=3_000, results=3))
    assert (found.kind, found.action, found.step) == ("price", "stop", 10)
    assert found.advice == "keep_off"


def test_ten_only_warns_about_a_group_built_elsewhere() -> None:
    found = _one(_group(spend_minor=3_000, results=3, ours=False))
    assert (found.action, found.step, found.advice) == ("warn", 10, "pause")


def test_ten_only_warns_while_the_group_learns() -> None:
    found = _one(_group(spend_minor=3_000, results=3, learning=True))
    assert (found.action, found.advice) == ("warn", "leave")


def test_a_group_with_no_usual_price_is_not_judged_on_price() -> None:
    assert judge(_group(spend_minor=9_000, results=1, usual=Usual())) == []


# -- nothing back ------------------------------------------------------------------------


def test_five_usual_prices_with_nothing_back_stops() -> None:
    found = _one(_group(spend_minor=500, results=0))
    assert (found.kind, found.action, found.advice) == ("fruitless", "stop", "keep_off")


def test_less_than_five_with_nothing_back_waits() -> None:
    assert judge(_group(spend_minor=499, results=0)) == []


def test_a_small_budget_s_dry_days_add_up() -> None:
    # 80 today, 510 since the last result four days ago.
    found = _one(_group(spend_minor=80, results=0, dry_spend_minor=510, dry_days=4))
    assert (found.kind, found.action, found.times) == ("fruitless", "stop", 510)
    assert judge(_group(spend_minor=80, dry_spend_minor=490, dry_days=4)) == []


def test_nothing_back_stops_a_learning_group_too() -> None:
    assert _one(_group(spend_minor=500, learning=True)).action == "stop"


def test_a_price_on_one_or_two_results_is_not_said() -> None:
    # Four usual prices on two leads: an hour's coin toss, not a price.
    assert judge(_group(spend_minor=800, results=2)) == []
    # Ten usual prices gone on them is enough to say it.
    found = _one(_group(spend_minor=1_000, results=2))
    assert (found.kind, found.action, found.step) == ("price", "warn", 5)


def test_nothing_back_elsewhere_waits_for_five_usual_prices() -> None:
    assert judge(_group(spend_minor=499, ours=False)) == []
    # Ours waits for the same five, and is stopped there.
    assert judge(_group(spend_minor=499)) == []
    assert _one(_group(spend_minor=500)).action == "stop"


def test_nothing_back_only_warns_elsewhere() -> None:
    found = _one(_group(spend_minor=500, ours=False))
    assert (found.action, found.advice) == ("warn", "pause")


# -- the first day -----------------------------------------------------------------------


def test_nothing_is_judged_in_the_first_day() -> None:
    assert judge(_group(spend_minor=900, results=0, hours_running=23.9)) == []
    assert judge(_group(spend_minor=900, results=1, hours_running=5)) == []


def test_a_page_that_is_down_does_not_wait_the_day() -> None:
    found = _one(_group(site_down=True, hours_running=1))
    assert (found.kind, found.action) == ("site_down", "stop")


def test_a_page_down_elsewhere_is_a_warning() -> None:
    assert _one(_group(site_down=True, ours=False)).action == "warn"


def test_an_unknown_age_is_read_as_old() -> None:
    assert _one(_group(spend_minor=500, hours_running=None)).kind == "fruitless"


# -- one finding a group -----------------------------------------------------------------


def test_a_price_rise_carries_its_causes_instead_of_more_messages() -> None:
    # Shown 1000 times for 320: CPM 320 against 200; 4 clicks: CTR 0.4 %.
    group = _group(spend_minor=1_500, results=3, impressions=4_700, link_clicks=19)
    found = _one(group)
    assert found.kind == "price"
    assert found.causes == ("cpm", "ctr")


def test_price_advice_is_the_stop_unless_learning() -> None:
    group = _group(spend_minor=1_500, results=3)
    assert _one(group).advice == "pause"
    assert _one(replace(group, learning=True)).advice == "leave"


def test_conversion_is_named_when_clicks_come_and_results_do_not() -> None:
    # Usual: CPM 200, CTR 1 % -> a click costs 20, a result 100 -> 5 clicks.
    # Today: 2000 showings for 400, 20 clicks, 1 result -> 20 clicks a result.
    group = _group(spend_minor=400, results=1, impressions=2_000, link_clicks=20)
    assert causes(group) == ("conversion",)


# -- an advert inside a group ------------------------------------------------------------


def test_a_weak_advert_beside_a_working_one_is_a_warning() -> None:
    group = _group(
        spend_minor=600,
        results=6,
        ads=(
            AdToday(ad_id="a1", spend_minor=300, results=6),
            AdToday(ad_id="a2", spend_minor=300, results=0),
        ),
    )
    found = _one(group)
    assert (found.kind, found.action, found.ad_id, found.advice) == (
        "weak_ad", "warn", "a2", "pause_ad",
    )  # fmt: skip


def test_the_only_advert_is_never_the_weak_one() -> None:
    group = _group(
        spend_minor=200, results=1, ads=(AdToday(ad_id="a1", spend_minor=300),)
    )
    assert judge(group) == []


def test_no_weak_advert_when_none_brings_results() -> None:
    group = _group(
        spend_minor=200,
        results=1,
        ads=(
            AdToday(ad_id="a1", spend_minor=300),
            AdToday(ad_id="a2", spend_minor=300),
        ),
    )
    assert judge(group) == []


def test_a_small_share_is_not_the_weak_advert() -> None:
    group = _group(
        spend_minor=1_300,
        results=10,
        ads=(
            AdToday(ad_id="a1", spend_minor=1_000, results=10),
            AdToday(ad_id="a2", spend_minor=300, results=0),
        ),
    )
    assert judge(group) == []


# -- rates -------------------------------------------------------------------------------


def test_a_fallen_click_rate_under_five_usual_prices_is_not_said() -> None:
    # 0.6 % against 1 %, and a result at 1.6 usual prices.
    group = _group(spend_minor=160, results=1, impressions=1_000, link_clicks=6)
    assert judge(group) == []


def test_a_fallen_click_rate_at_the_usual_price_is_only_a_day() -> None:
    group = _group(spend_minor=150, results=2, impressions=1_000, link_clicks=6)
    assert judge(group) == []


def test_a_fallen_click_rate_with_a_usual_price_gone_and_nothing_back() -> None:
    group = _group(spend_minor=100, results=0, impressions=1_000, link_clicks=6)
    assert judge(group) == []


def test_too_few_showings_say_nothing_about_a_rate() -> None:
    group = _group(spend_minor=160, results=1, impressions=999, link_clicks=1)
    assert judge(group) == []


def test_frequency_past_three() -> None:
    assert _one(_group(frequency=300)).kind == "frequency"
    assert judge(_group(frequency=299)) == []


def test_dear_showings_under_five_usual_prices_are_not_said() -> None:
    # CPM 400 against 200, the usual 1 % clicking, a result at twice usual.
    group = _group(spend_minor=400, results=2, impressions=1_000, link_clicks=10)
    assert judge(group) == []


# -- easing ------------------------------------------------------------------------------


def test_a_rise_is_over_under_two_usual_prices() -> None:
    assert eased(_group(spend_minor=199, results=1))
    assert not eased(_group(spend_minor=200, results=1))
    assert not eased(_group(spend_minor=500, results=0))


def test_a_first_cheap_result_of_the_morning_is_not_the_end() -> None:
    assert not eased(_group(spend_minor=40, results=1))


# -- a new group: only against itself ----------------------------------------------------

# Three results in its first days at 100 each: a price of its own, not a level.
START = Usual(cost_minor=100, source="start")


def _new(**changes: object) -> GroupToday:
    """Launched here two days ago, a day's budget of 500, no price yet."""
    base = _group(usual=Usual(), hours_running=48, day_budget_minor=500)
    return replace(base, **changes)  # type: ignore[arg-type]


def test_under_a_day_s_budget_with_nothing_back_nothing_is_said() -> None:
    assert judge(_new(spend_minor=499)) == []


def test_a_day_s_budget_with_nothing_back_is_a_warning() -> None:
    found = _one(_new(spend_minor=500))
    assert (found.kind, found.action, found.step, found.advice) == (
        "fruitless", "warn", 1, "pause",
    )  # fmt: skip


def test_the_first_days_money_adds_up_to_the_day_s_budget() -> None:
    found = _one(_new(spend_minor=100, dry_spend_minor=600, dry_days=2))
    assert found.action == "warn"


def test_three_days_on_with_no_result_ever_is_stopped() -> None:
    assert _one(_new(spend_minor=500, hours_running=71)).action == "warn"
    found = _one(_new(spend_minor=500, hours_running=72))
    assert (found.kind, found.action, found.step, found.advice) == (
        "fruitless", "stop", 2, "keep_off",
    )  # fmt: skip


def test_three_days_on_stops_a_learning_group_too() -> None:
    assert _one(_new(spend_minor=500, hours_running=80, learning=True)).action == "stop"


def test_three_days_on_with_no_money_gone_is_not_stopped() -> None:
    assert judge(_new(spend_minor=0, hours_running=200)) == []


def test_a_group_that_once_brought_a_result_is_only_warned() -> None:
    found = _one(_new(spend_minor=500, hours_running=200, past_results=2))
    assert (found.action, found.step) == ("warn", 1)


def test_a_new_group_built_elsewhere_is_only_warned() -> None:
    found = _one(_new(spend_minor=500, hours_running=200, ours=False))
    assert found.action == "warn"


def test_a_result_today_ends_the_dry_spell_of_a_new_group() -> None:
    assert judge(_new(spend_minor=5_000, results=1, hours_running=200)) == []


def test_without_a_day_s_budget_any_money_gone_counts() -> None:
    found = _one(_new(spend_minor=10, day_budget_minor=0))
    assert found.action == "warn"


def test_a_new_group_s_own_price_stops_it_for_nothing_back() -> None:
    found = _one(_new(usual=START, spend_minor=300))
    assert (found.kind, found.action) == ("fruitless", "stop")
    assert judge(_new(usual=START, spend_minor=299)) == []


def test_a_new_group_s_price_rise_is_never_a_stop() -> None:
    found = _one(_new(usual=START, spend_minor=3_000, results=3))
    assert (found.kind, found.action, found.step, found.advice) == (
        "price", "warn", 10, "pause",
    )  # fmt: skip
