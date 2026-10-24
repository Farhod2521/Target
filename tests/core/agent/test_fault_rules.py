"""An advert the provider stopped over its picture, and the picture that fixes it.

No database and no clock: the facts are built by hand, the way the other
rule tests build them.
"""

from typing import Any

import pytest
from adskit import ProviderName

from core.agent import (
    AccountFacts,
    AdFacts,
    AdSetFacts,
    Landing,
    LibraryImage,
    Policy,
    find,
    scan,
)
from core.agent.rules import BROKEN_PICTURE, REFUSED_AD, SITE_DOWN
from core.metrics import SegmentFigures, Totals

META = ProviderName("meta")
POLICY = Policy(max_per_run=0)

MENU = LibraryImage(asset_id="asset-menu", image_hash="menu", name="menu.png")
HALL = LibraryImage(asset_id="asset-hall", image_hash="hall", name="hall.png")


def advert(external_id: str, **overrides: Any) -> AdFacts:
    fields: dict[str, Any] = {
        "name": external_id,
        "delivery": "rejected",
        "figures": SegmentFigures(segment=external_id),
        "issue_codes": ("1487",),
        "issue_summary": "Image Not Found",
        "creative_kind": "link",
        "image_hash": "theirs",
    }
    fields.update(overrides)
    return AdFacts(**fields)


def group(*ads: AdFacts, **overrides: Any) -> AdSetFacts:
    return AdSetFacts(
        external_id=overrides.pop("external_id", "adset-1"),
        campaign_external_id=overrides.pop("campaign_external_id", "camp-1"),
        name="Qish aksiyasi",
        delivery=overrides.pop("delivery", "active"),
        totals=Totals(),
        daily_budget_minor=overrides.pop("daily_budget_minor", 200),
        is_learning=overrides.pop("is_learning", True),
        is_ours=overrides.pop("is_ours", True),
        ads=ads,
        **overrides,
    )


def account(*groups: AdSetFacts, library: tuple[LibraryImage, ...]) -> AccountFacts:
    return AccountFacts(
        provider=META,
        currency="USD",
        window_days=7,
        totals=Totals(),
        adsets=groups,
        library=library,
    )


def proposals(facts: AccountFacts) -> list[Any]:
    return [
        item
        for item in scan(account=facts, policy=POLICY)
        if item.rule == BROKEN_PICTURE
    ]


def test_a_picture_the_account_does_not_hold_gets_one_it_does() -> None:
    """Another account's picture, listed on this account's library edge:
    accepted into a creative, and the advert fails once it delivers."""
    (found,) = proposals(account(group(advert("ad-1")), library=(MENU, HALL)))

    assert found.kind == "new_picture"
    assert found.ref.id == "ad-1"
    assert found.parent_id == "adset-1"
    assert found.payload == {"asset_id": "asset-menu", "image_hash": "menu"}
    assert found.evidence["picture_name"] == "menu.png"


def test_a_picture_a_live_sibling_shows_is_preferred_over_the_newest() -> None:
    """The owner already chose that picture for this offer."""
    sibling = advert("ad-2", delivery="active", issue_codes=(), image_hash="hall")

    (found,) = proposals(account(group(advert("ad-1"), sibling), library=(MENU, HALL)))

    assert found.payload["asset_id"] == "asset-hall"


def test_a_sibling_in_another_group_of_the_campaign_counts_too() -> None:
    sibling = advert("ad-2", delivery="active", issue_codes=(), image_hash="hall")

    (found,) = proposals(
        account(
            group(advert("ad-1")),
            group(sibling, external_id="adset-2"),
            library=(MENU, HALL),
        )
    )

    assert found.payload["asset_id"] == "asset-hall"


def test_the_providers_words_name_a_picture_the_account_did_hold() -> None:
    """Held once and lost since: the hash is the account's, and the fault is
    still the picture - so the replacement is a different one."""
    lost = advert("ad-1", image_hash="menu")

    (found,) = proposals(account(group(lost), library=(MENU, HALL)))

    assert found.payload["asset_id"] == "asset-hall"


def test_an_advert_that_is_delivering_is_not_proposed_about() -> None:
    running = advert("ad-1", delivery="active")

    assert proposals(account(group(running), library=(MENU,))) == []


def test_a_fault_that_is_not_the_picture_gets_no_new_picture() -> None:
    """The account holds the picture and the provider named something else."""
    other = advert("ad-1", image_hash="menu", issue_summary="Ad Account Disabled")

    assert proposals(account(group(other), library=(MENU, HALL))) == []


def test_a_video_is_not_given_a_picture() -> None:
    video = advert("ad-1", creative_kind="video", image_hash="")

    assert proposals(account(group(video), library=(MENU,))) == []


def test_nothing_is_proposed_without_a_picture_to_offer() -> None:
    assert proposals(account(group(advert("ad-1")), library=())) == []


def test_a_campaign_built_elsewhere_is_left_to_its_owner() -> None:
    """A new creative is more than a stop or a budget."""
    inherited = group(advert("ad-1"), is_ours=False)

    assert proposals(account(inherited, library=(MENU,))) == []


def test_a_learning_group_does_not_hide_the_fault() -> None:
    """Nothing is being learned from an advert that is not delivering."""
    learning = group(advert("ad-1"), is_learning=True)

    assert len(proposals(account(learning, library=(MENU,)))) == 1


def test_every_stopped_advert_is_proposed_about_whatever_the_cap() -> None:
    """A fault is a fact, not an opinion to rank."""
    facts = account(
        group(advert("ad-1"), advert("ad-2"), advert("ad-3")),
        library=(MENU,),
    )

    found = find(account=facts, policy=POLICY)

    assert sorted(item.ref.id for item in found) == ["ad-1", "ad-2", "ad-3"]


# --- A refused advert --------------------------------------------------------
def refusals(facts: AccountFacts) -> list[Any]:
    return [
        item for item in scan(account=facts, policy=POLICY) if item.rule == REFUSED_AD
    ]


def test_a_refused_advert_is_proposed_as_one_with_new_words() -> None:
    refused = advert(
        "ad-1",
        issue_codes=(),
        issue_summary="",
        image_hash="menu",
        refusal="Personal Health: Ads may not imply knowledge of a condition.",
    )

    (found,) = refusals(account(group(refused), library=(MENU,)))

    assert found.kind == "new_ad"
    assert found.ref.id == "ad-1"
    assert found.evidence["cause"] == "refused"
    assert found.evidence["refusal"].startswith("Personal Health")


def test_a_promoted_post_keeps_its_words_on_the_post() -> None:
    post = advert("ad-1", creative_kind="post", refusal="Personal Health: ...")

    assert refusals(account(group(post), library=(MENU,))) == []


@pytest.mark.parametrize("delivery", ["paused", "paused_above", "finished"])
def test_a_switched_off_group_gets_no_fix_for_its_adverts(delivery: str) -> None:
    """The provider keeps calling a refused advert refused after the owner
    switches its group or campaign off. A fix there is a fix for nothing."""
    refused = advert("ad-1", image_hash="menu", refusal="Personal Health.")
    broken = advert("ad-2")
    facts = account(group(refused, broken, delivery=delivery), library=(MENU,))

    assert refusals(facts) == []
    assert proposals(facts) == []


def test_an_advert_nobody_refused_gets_no_new_words() -> None:
    assert refusals(account(group(advert("ad-1")), library=(MENU,))) == []


# --- A page that does not open ---------------------------------------------
def stops(facts: AccountFacts) -> list[Any]:
    return [
        item for item in scan(account=facts, policy=POLICY) if item.rule == SITE_DOWN
    ]


def test_a_group_sending_people_to_a_dead_page_is_proposed_a_stop() -> None:
    down = group(landing=Landing(down_urls=("https://shop.uz",)), is_learning=False)

    (found,) = stops(account(down, library=()))

    assert (found.kind, found.ref.level, found.ref.id) == ("pause", "adset", "adset-1")
    assert found.evidence["down_url"] == "https://shop.uz"


def test_a_campaign_built_elsewhere_can_be_stopped_too() -> None:
    """A stop is the owner's own protection, never a rewrite."""
    down = group(landing=Landing(down_urls=("https://shop.uz",)), is_ours=False)

    assert len(stops(account(down, library=()))) == 1


def test_a_group_already_stopped_is_not_proposed_a_stop() -> None:
    down = group(landing=Landing(down_urls=("https://shop.uz",)), delivery="paused")

    assert stops(account(down, library=())) == []
