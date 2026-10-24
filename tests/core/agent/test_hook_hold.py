"""Where a video loses people: the opening, the middle, or neither.

Hook rate is three-second views over impressions; hold rate is ThruPlays
over three-second views. Against the pair's other videos where there are
any, against the brief's starting values where there are none.
"""

from core.agent import AdSetFacts, Funnel, Policy
from core.agent.benchmark import Benchmark
from core.agent.signals import signals
from core.metrics import Totals

POLICY = Policy()


def video(*, views_3s: int, thruplays: int) -> AdSetFacts:
    funnel = Funnel(
        spend_minor=50_000,
        impressions=10_000,
        link_clicks=150,
        video_plays=8_000,
        video_views_3s=views_3s,
        video_thruplays=thruplays,
    )
    return AdSetFacts(
        external_id="g",
        campaign_external_id="c",
        name="Video",
        delivery="active",
        totals=Totals(spend_minor=50_000, impressions=10_000),
        days_with_spend=7,
        counts_leads=True,
        funnel=funnel,
    )


def noticed(item: AdSetFacts, bench: Benchmark | None = None) -> set[str]:
    return set(signals(item=item, bench=bench or Benchmark(), policy=POLICY))


def test_a_weak_opening_with_a_good_middle_is_the_opening() -> None:
    found = noticed(video(views_3s=1_000, thruplays=300))

    assert "weak_hook" in found
    assert "weak_hold" not in found


def test_a_good_opening_with_a_weak_middle_is_the_middle() -> None:
    found = noticed(video(views_3s=3_000, thruplays=150))

    assert "weak_hook" not in found
    assert "weak_hold" in found


def test_both_good_is_neither() -> None:
    found = noticed(video(views_3s=3_000, thruplays=600))

    assert not found & {"weak_hook", "weak_hold"}


def test_the_pairs_other_videos_are_the_bar_when_there_are_any() -> None:
    """Thirty percent is a fine opening by the brief and a weak one beside
    videos that stop half the people shown them."""
    strong = Benchmark(
        video_impressions=10_000, video_views_3s=5_000, video_thruplays=1_000
    )

    assert "weak_hook" in noticed(video(views_3s=3_000, thruplays=600), strong)
