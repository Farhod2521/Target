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
    assert [price_step(t) for t in (299, 300, 399, 400, 499, 500, 900)] == [
        0, 3, 3, 4, 4, 5, 5,
    ]  # fmt: skip


def test_under_three_usual_prices_nothing_is_said() -> None:
    assert judge(_group(spend_minor=299, results=1)) == []


def test_three_usual_prices_is_a_warning() -> None:
    found = _one(_group(spend_minor=320, results=1))
    assert (found.kind, found.action, found.step, found.times) == (
        "price", "warn", 3, 320,
    )  # fmt: skip


def test_four_is_a_second_warning_that_advises_the_stop() -> None:
    found = _one(_group(spend_minor=410, results=1))
    assert (found.action, found.step, found.advice) == ("warn", 4, "pause")


def test_five_stops_what_was_launched_here() -> None:
    found = _one(_group(spend_minor=500, results=1))
    assert (found.kind, found.action, found.step) == ("price", "stop", 5)
    assert found.advice == "keep_off"


def test_five_only_warns_about_a_group_built_elsewhere() -> None:
    found = _one(_group(spend_minor=500, results=1, ours=False))
    assert (found.action, found.step, found.advice) == ("warn", 5, "pause")


def test_five_only_warns_while_the_group_learns() -> None:
    found = _one(_group(spend_minor=500, results=1, learning=True))
    assert (found.action, found.advice) == ("warn", "leave")


def test_a_group_with_no_usual_price_is_not_judged_on_price() -> None:
    assert judge(_group(spend_minor=9_000, results=1, usual=Usual())) == []


# -- nothing back ------------------------------------------------------------------------


def test_three_usual_prices_with_nothing_back_stops() -> None:
    found = _one(_group(spend_minor=300, results=0))
    assert (found.kind, found.action, found.advice) == ("fruitless", "stop", "keep_off")


def test_less_than_three_with_nothing_back_waits() -> None:
    assert judge(_group(spend_minor=299, results=0)) == []


def test_nothing_back_stops_a_learning_group_too() -> None:
    assert _one(_group(spend_minor=300, learning=True)).action == "stop"


def test_nothing_back_only_warns_elsewhere() -> None:
    found = _one(_group(spend_minor=300, ours=False))
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
    assert _one(_group(spend_minor=300, hours_running=None)).kind == "fruitless"


# -- one finding a group -----------------------------------------------------------------


def test_a_price_rise_carries_its_causes_instead_of_more_messages() -> None:
    # Shown 1000 times for 320: CPM 320 against 200; 4 clicks: CTR 0.4 %.
    group = _group(spend_minor=320, results=1, impressions=1_000, link_clicks=4)
    found = _one(group)
    assert found.kind == "price"
    assert found.causes == ("cpm", "ctr")


def test_price_advice_by_cause() -> None:
    # CPM alone: the auction, leave it.
    # 1000 showings for 600 (three usual CPMs), the usual 1 % clicking, the
    # usual five clicks a result.
    cpm_only = _group(spend_minor=600, results=2, impressions=1_000, link_clicks=10)
    assert causes(cpm_only) == ("cpm",)
    assert _one(cpm_only).advice == "leave"
    # The click rate: less money meanwhile - where the budget is the group's.
    ctr = _group(spend_minor=320, results=1, impressions=2_000, link_clicks=10)
    assert "ctr" in causes(ctr)
    assert _one(ctr).advice == "budget_down"
    assert _one(replace(ctr, own_budget=False)).advice == "leave"


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


def test_a_fallen_click_rate_with_a_climbing_price_asks_for_a_creative() -> None:
    # 0.6 % against 1 %, and a result at 1.6 usual prices.
    group = _group(spend_minor=160, results=1, impressions=1_000, link_clicks=6)
    found = _one(group)
    assert (found.kind, found.advice) == ("ctr", "add_creative")


def test_a_fallen_click_rate_at_the_usual_price_is_only_a_day() -> None:
    group = _group(spend_minor=150, results=2, impressions=1_000, link_clicks=6)
    assert judge(group) == []


def test_a_fallen_click_rate_with_a_usual_price_gone_and_nothing_back() -> None:
    group = _group(spend_minor=100, results=0, impressions=1_000, link_clicks=6)
    assert _one(group).kind == "ctr"


def test_too_few_showings_say_nothing_about_a_rate() -> None:
    group = _group(spend_minor=160, results=1, impressions=999, link_clicks=1)
    assert judge(group) == []


def test_frequency_past_three() -> None:
    assert _one(_group(frequency=300)).kind == "frequency"
    assert judge(_group(frequency=299)) == []


def test_dear_showings_with_a_climbing_price_are_left() -> None:
    # CPM 400 against 200, the usual 1 % clicking, a result at twice usual.
    group = _group(spend_minor=400, results=2, impressions=1_000, link_clicks=10)
    found = _one(group)
    assert (found.kind, found.advice) == ("cpm", "leave")


# -- easing ------------------------------------------------------------------------------


def test_a_rise_is_over_under_two_usual_prices() -> None:
    assert eased(_group(spend_minor=199, results=1))
    assert not eased(_group(spend_minor=200, results=1))
    assert not eased(_group(spend_minor=500, results=0))


def test_a_first_cheap_result_of_the_morning_is_not_the_end() -> None:
    assert not eased(_group(spend_minor=40, results=1))
