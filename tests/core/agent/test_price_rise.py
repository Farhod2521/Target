"""core/agent/price_rise: the usual price, three times it, and why (TZ 1.2-1.6)."""

from dataclasses import replace

from core.agent.price_rise import (
    Figures,
    Usual,
    causes,
    eased,
    risen,
    times,
    usual_of,
)

# An advert that brings a result for $2.00: 10 000 shown, 200 link clicks, 20
# results, 2 500 people, a video watched 3 seconds by 2 700 and through by 900.
USUAL = Figures(
    spend_minor=4_000,
    impressions=10_000,
    results=20,
    link_clicks=200,
    clicks=300,
    reach=2_500,
    views_3s=2_700,
    thruplays=900,
)


def _usual() -> Usual:
    found = usual_of([USUAL, USUAL, USUAL], source="account_history")
    assert found is not None
    return found


def test_the_usual_price_is_the_median_of_three_adverts_that_qualify() -> None:
    dear = replace(USUAL, spend_minor=8_000)
    found = usual_of([USUAL, dear, USUAL], source="account_history")

    assert found is not None
    assert (found.cost, found.adverts, found.source) == (200, 3, "account_history")
    assert found.steps["ctr"] == 2.0
    assert found.steps["hook"] == 27.0


def test_two_adverts_or_small_ones_make_no_usual_price() -> None:
    small = replace(USUAL, impressions=999)
    few = replace(USUAL, results=4)

    assert usual_of([USUAL, USUAL], source="account_history") is None
    assert usual_of([USUAL, USUAL, small, few], source="account_history") is None


def test_three_times_the_usual_price_rises() -> None:
    usual = _usual()

    assert risen(replace(USUAL, spend_minor=6_000, results=10), usual)
    assert not risen(replace(USUAL, spend_minor=5_999, results=10), usual)
    assert times(replace(USUAL, spend_minor=6_200, results=10), usual) == 3.1


def test_nothing_back_rises_on_three_usual_prices_spent() -> None:
    usual = _usual()

    assert risen(replace(USUAL, spend_minor=600, results=0), usual)
    assert not risen(replace(USUAL, spend_minor=599, results=0), usual)


def test_under_twice_the_usual_price_starts_again() -> None:
    usual = _usual()

    assert eased(replace(USUAL, spend_minor=3_999, results=10), usual)
    assert not eased(replace(USUAL, spend_minor=4_000, results=10), usual)
    assert not eased(replace(USUAL, spend_minor=100, results=0), usual)


def test_the_furthest_step_comes_first_and_two_at_most() -> None:
    now = replace(
        USUAL,
        views_3s=900,  # hook 9% against 27%: a third
        thruplays=300,
        link_clicks=120,  # CTR 1.2% against 2%: 0.6
        results=12,
        rankings={"quality": "below_average_10"},
    )

    found = causes(now, _usual())

    assert [cause.key for cause in found] == ["hook", "ctr"]
    assert round(found[0].ratio, 2) == 0.33


def test_a_dearer_click_is_the_cpm_s_or_the_ctr_s_doing() -> None:
    now = replace(USUAL, link_clicks=130)  # CTR 0.65 of usual, CPC 1.54

    assert [cause.key for cause in causes(now, _usual())] == ["ctr"]


def test_hook_and_hold_are_read_on_videos_only() -> None:
    picture = replace(USUAL, views_3s=0, thruplays=0, link_clicks=120)

    assert [cause.key for cause in causes(picture, _usual())] == ["ctr"]


def test_a_chat_s_last_step_is_results_over_every_click() -> None:
    usual = usual_of([replace(USUAL, chat=True)] * 3, source="account_history")
    assert usual is not None
    now = replace(USUAL, chat=True, results=8, clicks=300)

    assert [cause.key for cause in causes(now, usual)] == ["conversion"]


def test_meta_s_ranking_at_bottom_fifth_is_a_cause() -> None:
    now = replace(
        USUAL, rankings={"quality": "below_average_20", "engagement": "average"}
    )

    found = causes(now, _usual())

    assert [(cause.key, cause.ranking) for cause in found] == [("ranking", "quality")]
    assert not causes(
        replace(USUAL, rankings={"quality": "below_average_35"}), _usual()
    )


def test_no_step_past_its_bar_is_no_cause() -> None:
    """Every step a little worse - CPM 1.2 times, CTR 0.85 of usual - and
    none past its bar."""
    now = replace(USUAL, spend_minor=4_800, link_clicks=170, results=17)

    assert causes(now, _usual()) == []
