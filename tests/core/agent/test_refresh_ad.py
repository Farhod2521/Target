"""core/agent/rules/refresh: a new picture where a group's advert is being ignored.

No database and no clock. The cause is the diagnosis's - pinned in
``test_diagnosis`` - and what is argued here is what gets proposed from it,
on which advert, with which picture, and on whose figures the promise is
graded.
"""

from typing import Any

from core.agent import (
    JUDGED_ON_PARENT,
    NOT_WORKED,
    UNCLEAR,
    WORKED,
    AccountFacts,
    AdFacts,
    AdSetFacts,
    Aftermath,
    Half,
    Landing,
    assess,
)
from core.agent.ad_facts import LibraryImage
from core.agent.before_after import before_after
from core.agent.rules import REFRESH_AD, refresh_ad, scan
from core.metrics import SegmentFigures, Totals
from tests.core.agent.test_diagnosis import META, POLICY, group, steady

# The diagnosis test's "nobody clicks" group, with leads that cost too much
# rather than none - the case no stop answers first.
IGNORED: dict[str, Any] = {"link_clicks": 500, "leads": 10}

# The account's own pictures, newest first. The first is the one the group
# already shows.
LIBRARY = (
    LibraryImage(asset_id="asset-old", image_hash="hash-big", name="Eski"),
    LibraryImage(asset_id="asset-new", image_hash="hash-new", name="Bahor"),
)


def advert(
    segment: str,
    spend: int,
    delivery: str = "active",
    kind: str = "link",
    image_hash: str = "",
) -> AdFacts:
    return AdFacts(
        name=segment,
        delivery=delivery,
        figures=SegmentFigures(segment=segment, spend_minor=spend),
        creative_kind=kind,
        image_hash=image_hash or f"hash-{segment.removeprefix('ad-')}",
    )


def ours(**overrides: Any) -> AdSetFacts:
    """The judged group, built by this product, with two adverts in it."""
    overrides.setdefault("is_ours", True)
    overrides.setdefault("ads", (advert("ad-small", 60_000), advert("ad-big", 240_000)))
    return group(**overrides)


def account(
    *adsets: AdSetFacts, library: tuple[LibraryImage, ...] = LIBRARY
) -> AccountFacts:
    return AccountFacts(
        provider=META,
        currency="USD",
        window_days=7,
        totals=Totals(),
        adsets=(*adsets, steady()),
        library=library,
    )


def test_an_ignored_advert_gets_a_new_picture_on_the_one_carrying_the_group() -> None:
    found = refresh_ad(account=account(ours(**IGNORED)), policy=POLICY)

    assert [
        (item.kind, item.ref.level, item.ref.id, item.parent_id) for item in found
    ] == [("new_picture", "ad", "ad-big", "judged")]
    assert found[0].payload == {"asset_id": "asset-new", "image_hash": "hash-new"}
    assert found[0].evidence["cause"] == "weak_creative"
    assert found[0].evidence["ad_spend_share_pct"] == 80
    assert found[0].weight == 300_000


def test_the_price_it_is_judged_on_rides_along() -> None:
    [found] = refresh_ad(account=account(ours(**IGNORED)), policy=POLICY)

    assert {key: found.evidence[key] for key in ("outcome", "results")} == {
        "outcome": "lead",
        "results": 10,
    }
    # The account's price is the steady neighbour's alone.
    assert (found.evidence["cost_minor"], found.evidence["account_cost_minor"]) == (
        30_000,
        10_000,
    )


def test_the_picture_is_one_the_group_is_not_showing() -> None:
    """The whole group is what people stopped looking at."""
    library = (
        LibraryImage(asset_id="asset-small", image_hash="hash-small"),
        *LIBRARY,
    )

    [found] = refresh_ad(
        account=account(ours(**IGNORED), library=library), policy=POLICY
    )

    assert found.payload["asset_id"] == "asset-new"


def test_nothing_new_in_the_library_leaves_nothing_to_propose() -> None:
    """The waiting list asks for a picture instead - see the notes selector."""
    shown_only = (LibraryImage(asset_id="asset-old", image_hash="hash-big"),)

    assert (
        refresh_ad(account=account(ours(**IGNORED), library=shown_only), policy=POLICY)
        == []
    )


def test_a_video_or_a_post_is_not_given_a_picture() -> None:
    video = ours(ads=(advert("ad-big", 300_000, kind="video"),), **IGNORED)

    assert refresh_ad(account=account(video), policy=POLICY) == []


def test_a_tired_audience_is_left_to_the_frequency_message() -> None:
    """The morning's frequency levels say "a new advert" with their own two
    buttons; a picture card beside them would be the same advice twice."""
    tired = ours(
        link_clicks=1_300,
        leads=0,
        early=Half(days=3, impressions=40_000, link_clicks=800),
        late=Half(days=4, impressions=60_000, link_clicks=500),
        week_frequency=220,
    )

    assert refresh_ad(account=account(tired), policy=POLICY) == []


def test_cheap_conversations_get_nothing_however_few_click() -> None:
    """The advert that was nearly rewritten: its conversations cost what
    they usually do, so nothing about it is a problem to answer."""
    working = ours(
        counts_leads=False,
        outcome="chat",
        leads=0,
        link_clicks=1_120,
        results=35,
        spend=875,
    )
    neighbour = steady(
        counts_leads=False,
        outcome="chat",
        leads=0,
        link_clicks=2_500,
        results=35,
        spend=875,
    )

    assert refresh_ad(account=account(working, neighbour), policy=POLICY) == []


def test_a_campaign_built_elsewhere_is_not_changed() -> None:
    elsewhere = ours(is_ours=False, **IGNORED)

    assert refresh_ad(account=account(elsewhere), policy=POLICY) == []


def test_a_group_that_is_fine_gets_nothing() -> None:
    assert refresh_ad(account=account(ours()), policy=POLICY) == []


def test_a_form_in_the_way_is_not_answered_with_a_picture() -> None:
    down = ours(landing=Landing(down_urls=("https://osh.example/",)), **IGNORED)

    assert refresh_ad(account=account(down), policy=POLICY) == []


def test_no_advert_carrying_the_group_leaves_nothing_to_change() -> None:
    stopped = ours(ads=(advert("ad-1", 300_000, delivery="paused"),), **IGNORED)

    assert refresh_ad(account=account(stopped), policy=POLICY) == []


def test_the_scan_offers_it_when_nothing_about_the_whole_group_is() -> None:
    found = scan(account=account(ours(**IGNORED)), policy=POLICY)

    assert (REFRESH_AD, "ad-big") in {(item.rule, item.ref.id) for item in found}


# --- the promise ------------------------------------------------------------
PRICED: dict[str, Any] = {"days": 7, "outcome": "chat", "cost_minor": 50}


def _verdict(results: int, spend: int = 4_000, evidence: Any = None) -> Any:
    return assess(
        rule=REFRESH_AD,
        evidence=PRICED if evidence is None else evidence,
        after=Aftermath(
            totals=Totals(spend_minor=spend, impressions=10_000, results=results),
            link_clicks=90,
            days=4,
        ),
        min_days=3,
    )


def test_it_is_graded_on_the_group_it_was_made_for() -> None:
    """The replaced advert is switched off; only the group runs through."""
    assert REFRESH_AD in JUDGED_ON_PARENT


def test_a_cheaper_conversation_is_what_it_promised() -> None:
    assert _verdict(results=100).outcome == WORKED
    assert _verdict(results=60).outcome == NOT_WORKED


def test_money_since_with_no_result_is_a_change_that_failed() -> None:
    assert _verdict(results=0).outcome == NOT_WORKED


def test_a_group_that_stopped_spending_cannot_say() -> None:
    assert _verdict(results=0, spend=0).outcome == UNCLEAR


def test_a_proposal_without_a_price_is_graded_on_its_click_rate() -> None:
    old = {"days": 7, "link_ctr_bp": 50}

    assert _verdict(results=0, evidence=old).outcome == WORKED


def test_the_record_compares_the_price_it_was_decided_on() -> None:
    change = before_after(
        rule=REFRESH_AD,
        evidence={**PRICED, "link_ctr_bp": 50},
        after={"days": 4, "spend_minor": 4_000, "cost_minor": 40},
    )

    assert change is not None
    assert (change.measure, change.before, change.after, change.outcome) == (
        "cost_per_result",
        50,
        40,
        "chat",
    )
