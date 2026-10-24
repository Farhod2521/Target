"""Where an ad sends people, and why that is not Meta's own field.

The whole of this file exists because of one line in Meta's own table:
``OUTCOME_TRAFFIC`` accepts ``UNDEFINED``, ``MESSENGER``, ``WHATSAPP`` and
``PHONE_CALL`` - and **not** ``WEBSITE``, which ``OUTCOME_SALES`` does
accept. Two goals that send somebody to the same website, and only one of
them may say so in that field.

So "does this goal go to a site" cannot be read off ``destination_type``,
and the catalogue answers it in the domain's own word instead. What is
pinned below is that the two stay separate, and that the traffic presets
never get their (wrong) ``destination_type: WEBSITE`` written back.
"""

from pathlib import Path

import pytest

from core.targeting import (
    DELIVERABLE,
    DESTINATIONS,
    BusinessProfile,
    CatalogError,
    ConversionSource,
    ConversionSourceMissing,
    DestinationLinkMissing,
    NoInterestsChosen,
    OnboardingAnswers,
    PresetCatalog,
    build,
    fallback,
    validate_launchable,
)
from core.targeting.presets import CATALOG_DIR

CATALOG = PresetCatalog.from_directory(CATALOG_DIR)
PROVIDER = "meta"
# What Meta's ODAX table lets a traffic ad set send as ``destination_type``,
# minus ``UNDEFINED``, which is returned only in read mode - and the
# Instagram profile, which the table predates and the profile visit ads
# guide names for this objective.
TRAFFIC_DESTINATIONS = frozenset(
    {"", "MESSENGER", "WHATSAPP", "PHONE_CALL", "INSTAGRAM_PROFILE"}
)
SITE = "https://dokon.uz/yozgi-chegirma"

SHOP = BusinessProfile(
    name="Do'kon", category="ecommerce", country_code="UZ", city="Tashkent"
)
PIXEL = ConversionSource(external_id="123456789", name="Do'kon pixeli")


def every_preset() -> list:
    presets = []
    for category in CATALOG.categories(provider=PROVIDER):
        presets.extend(CATALOG.goals(provider=PROVIDER, category=category.key))
    return presets


def built(goal: str, *, link: str = SITE, conversion: ConversionSource | None = None):
    return build(
        provider=PROVIDER,
        answers=OnboardingAnswers(
            category="ecommerce",
            goal=goal,
            daily_budget_minor=1000,
            # Pinned, because the interest gate is not what this file is
            # about and the default mode does not require one.
            targeting_mode="interests",
        ),
        business=SHOP,
        catalog=CATALOG,
        currency="USD",
        geo=fallback(country_code="UZ"),
        conversion=conversion,
        link=link,
    )


# --- The catalogue answers in the domain's word --------------------------
def test_every_preset_names_a_destination_the_domain_knows() -> None:
    """Required, not defaulted. A typo falling through to "cannot be built"
    takes a working goal off the first wizard screen with no error."""
    for preset in every_preset():
        assert preset.sends_to in DESTINATIONS, preset.key


def test_every_preset_names_a_button_except_the_ones_the_channel_names() -> None:
    """On the preset because it follows from the goal, like the
    optimisation goal beside it. The alternative is a branch on the goal's
    name inside the one module allowed to be provider-shaped.

    A chat goal is the exception and names neither the button nor the ad
    set destination: Meta pairs the two, and which pair applies is the
    owner's answer about where the conversation opens. Pinned in
    ``test_chat.py``."""
    for preset in every_preset():
        if preset.opens_chat:
            assert preset.call_to_action == "", preset.key
            assert preset.destination_type == "", preset.key
        else:
            assert preset.call_to_action, preset.key


def test_a_preset_with_no_destination_is_refused(tmp_path: Path) -> None:
    (tmp_path / "one.yaml").write_text(
        """
provider: meta
category: cafe
label: "Kafe"
version: 1
targeting_base: {age_min: 20}
presets:
  - {goal: calls, label: "A", objective: O, optimization_goal: G,
     billing_event: B, call_to_action: CALL_NOW}
""",
        encoding="utf-8",
    )

    with pytest.raises(CatalogError) as caught:
        PresetCatalog.from_directory(tmp_path)

    assert "sends_to" in str(caught.value)


def test_a_destination_the_domain_does_not_know_is_refused(tmp_path: Path) -> None:
    """A fallback here would be a goal that silently stops being offered."""
    (tmp_path / "one.yaml").write_text(
        """
provider: meta
category: cafe
label: "Kafe"
version: 1
targeting_base: {age_min: 20}
presets:
  - {goal: calls, label: "A", objective: O, optimization_goal: G,
     billing_event: B, sends_to: carrier_pigeon, call_to_action: CALL_NOW}
""",
        encoding="utf-8",
    )

    with pytest.raises(CatalogError) as caught:
        PresetCatalog.from_directory(tmp_path)

    assert "carrier_pigeon" in str(caught.value)


# --- The finding: two fields, two questions ------------------------------
def test_a_traffic_goal_sends_only_a_destination_meta_lists_for_it() -> None:
    """Meta's table gives OUTCOME_TRAFFIC ``MESSENGER``, ``WHATSAPP`` and
    ``PHONE_CALL`` and no ``WEBSITE``, and this is the test that keeps one
    out of the traffic presets. A traffic goal that goes to a site sends
    nothing."""
    for preset in every_preset():
        if preset.objective != "OUTCOME_TRAFFIC":
            continue
        assert preset.destination_type in TRAFFIC_DESTINATIONS, preset.key
        if preset.sends_to == "website":
            assert preset.destination_type == "", preset.key


def test_a_sales_goal_does_send_one() -> None:
    """The same website, the other objective, and Meta does list it there."""
    for preset in every_preset():
        if preset.objective == "OUTCOME_SALES":
            assert preset.destination_type == "WEBSITE", preset.key


def test_the_two_goals_agree_about_the_site_and_disagree_about_the_field() -> None:
    """The whole of why ``sends_to`` exists, in one assertion."""
    sales = CATALOG.find(provider=PROVIDER, category="ecommerce", goal="sales")
    traffic = CATALOG.find(provider=PROVIDER, category="ecommerce", goal="traffic")

    assert sales.sends_to == traffic.sends_to == "website"
    assert sales.destination_type != traffic.destination_type


def test_reading_the_provider_field_would_have_closed_the_traffic_goal() -> None:
    """Stated as the counterfactual, because it is the mistake this shape
    was chosen to avoid rather than an accident it happens to survive."""
    traffic = CATALOG.find(provider=PROVIDER, category="ecommerce", goal="traffic")

    assert traffic.destination_type not in {"ON_AD", "WEBSITE"}
    assert traffic.is_deliverable is True


# --- Which goals are open ------------------------------------------------
def test_only_the_six_shapes_the_sequence_can_build_are_deliverable() -> None:
    assert {"form", "website", "chat", "phone", "nothing", "profile"} == DELIVERABLE


def test_the_goals_now_offered_are_every_one_but_the_store() -> None:
    """Named rather than counted. A count passes when one goal quietly
    replaces another, which is exactly the change worth catching.

    ``awareness`` is in this set and is not on the wizard - it is
    deliverable and withdrawn, which are two different questions with two
    different answers. See ``shared.presets.offered_goals``.
    """
    offered = {p.goal for p in every_preset() if p.is_deliverable}

    assert offered == {
        "leads",
        "sales",
        "traffic",
        "site_leads",
        "messages",
        "calls",
        "awareness",
        "views",
        "profile_visits",
    }


def test_the_store_goal_stays_closed_and_not_for_our_own_reasons() -> None:
    """The one destination this product does not build, and the only one
    whose blocker is not in this repository.

    Meta optimises and reports a store visit against a **Place Page Set** -
    ``promoted_object: {place_page_set_id}`` - which is built from a parent
    Page with child location Pages under it. A single shop with a single
    Page is not that, and ``STORE_VISITS`` stopped being an optimisation
    goal at all: v26.0's enum does not contain it.

    Locked here rather than only written down, because the tempting fix is
    to open it as an ordinary local reach campaign with a "Get directions"
    button. That ad is real and it is not what the label promises: nothing
    would optimise for a visit and nothing would report one."""
    closed = {p.goal for p in every_preset() if not p.is_deliverable}

    assert closed == {"store_visits"}


def test_a_form_is_built_only_for_a_form_goal() -> None:
    """The one step the sequence cannot undo - Meta refuses a DELETE on a
    lead form - so a goal that does not need one must not make one."""
    for preset in every_preset():
        assert preset.needs_lead_form is (preset.sends_to == "form"), preset.key


def test_a_link_is_required_only_for_a_website_goal() -> None:
    for preset in every_preset():
        assert preset.needs_link is (preset.sends_to == "website"), preset.key


# --- What the built spec carries -----------------------------------------
def test_the_built_spec_carries_the_destination_and_the_button() -> None:
    """Carried rather than looked up again: the launch sequence has no
    catalogue and must not grow one."""
    spec = built("sales", conversion=PIXEL)

    assert spec.sends_to == "website"
    assert spec.call_to_action == "SHOP_NOW"
    assert spec.needs_link is True
    assert spec.needs_lead_form is False


def test_a_lead_goal_carries_the_other_answers() -> None:
    spec = built("leads")

    assert spec.needs_lead_form is True
    assert spec.needs_link is False
    assert spec.call_to_action == "SIGN_UP"


def test_the_link_travels_through_untouched() -> None:
    """Whether a given address is one the provider will accept is the
    provider's rule; this package does not know which hosts are theirs."""
    assert built("traffic", link=SITE).link_url == SITE


# --- The gate ------------------------------------------------------------
def test_a_website_goal_with_no_address_is_refused() -> None:
    """Refused rather than filled in. A fallback would point paid traffic
    at a page the advertiser never named and look like success."""
    with pytest.raises(DestinationLinkMissing):
        validate_launchable(built("traffic", link=""))


def test_the_address_is_checked_before_the_pixel() -> None:
    """Both are missing here. The address is the one whose failure would
    otherwise be invisible, so it is the one that gets named."""
    with pytest.raises(DestinationLinkMissing):
        validate_launchable(built("sales", link=""))


def test_the_address_is_checked_before_the_interests() -> None:
    with pytest.raises(DestinationLinkMissing):
        validate_launchable(built("traffic", link=""))


def test_a_goal_that_asks_for_no_address_is_never_stopped_by_this_rule() -> None:
    """Most of the catalogue. Half these businesses have no website."""
    with pytest.raises(NoInterestsChosen):
        validate_launchable(built("leads", link=""))


def test_a_sales_goal_with_an_address_still_needs_its_pixel() -> None:
    """The link gate passing does not make the pixel gate optional."""
    with pytest.raises(ConversionSourceMissing):
        validate_launchable(built("sales"))


def test_a_traffic_goal_needs_no_pixel() -> None:
    """Nothing off-site is being optimised towards, so nothing reports it."""
    spec = built("traffic")

    assert spec.needs_conversion_source is False
    with pytest.raises(NoInterestsChosen):
        validate_launchable(spec)
