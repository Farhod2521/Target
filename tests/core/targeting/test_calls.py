"""Goals whose ad dials a number, and the one whose ad has no button.

Two destinations that look unrelated and are pinned together because they
fail the same way: Meta accepts each of them built as something else and
runs the ad.

* **A call ad with no number is a website ad.** The number lives in
  ``call_to_action.value.link``, the same key an ordinary ad puts an
  address in - so an unanswered number does not leave the button empty, it
  leaves the button pointing at whatever link the creative was filled with.
* **An awareness ad with a button is a website ad too.** The creative's
  link falls back to this deployment's own front page for every goal that
  needs no address of its own, so a ``LEARN_MORE`` beside
  ``sends_to: nothing`` is a working button to our own site.

Neither is refused anywhere on the provider's side. That is the whole
reason these rules are here rather than waited for.

How the number reaches Meta is pinned in
``tests/packages/test_metaads_calls.py``; how it reaches a customer in
``tests/apps/ads/test_launch_calls.py``.
"""

from pathlib import Path

import pytest

from core.targeting import (
    BusinessProfile,
    CatalogError,
    DestinationLinkMissing,
    Interest,
    OnboardingAnswers,
    PhoneNumberMissing,
    PresetCatalog,
    build,
    dialable,
    fallback,
    is_local,
    validate_launchable,
)
from core.targeting.calls import region_of
from core.targeting.destinations import needs_phone, shows_a_button

PROVIDER = "meta"
CATALOG = PresetCatalog.from_directory(
    Path(__file__).resolve().parents[3] / "core" / "targeting" / "catalog"
)
CAFE = BusinessProfile(name="Osh Markazi", category="restaurant", country_code="UZ")

# A real Uzbek mobile, in the two shapes a person actually types it.
TYPED = "90 123 45 67"
E164 = "+998901234567"
# A real Russian mobile. Valid, dialable, and the wrong country for an ad
# shown in Uzbekistan - which is the failure Meta names and does not refuse.
FOREIGN = "+79161234567"

# Every gate but the destination ones still applies to these goals: an ad
# set has to be aimed at somebody. Supplied on every build below so that
# what each test refuses is the thing it is about.
CONFIRMED = (Interest(label="Restoranlar", query="Restaurants", external_id="6003"),)


def every_preset() -> list:
    return [
        CATALOG.find(provider=PROVIDER, category=category.key, goal=preset.goal)
        for category in CATALOG.categories(provider=PROVIDER)
        for preset in CATALOG.goals(provider=PROVIDER, category=category.key)
    ]


def built(goal: str, *, phone: str = E164, category: str = "restaurant"):
    return build(
        provider=PROVIDER,
        answers=OnboardingAnswers(
            category=category,
            goal=goal,
            daily_budget_minor=1000,
            interests=CONFIRMED,
        ),
        business=CAFE,
        catalog=CATALOG,
        currency="USD",
        geo=fallback(country_code="UZ"),
        phone=phone,
    )


def _write(path: Path, body: str) -> None:
    (path / "one.yaml").write_text(body, encoding="utf-8")


# --- What the catalogue says ---------------------------------------------
def test_every_calls_preset_carries_the_four_provider_words_meta_names() -> None:
    """The four words named rather than counted.

    Meta's call ads guide builds a call ad under the traffic objective:
    ``PHONE_CALL`` as the destination, ``QUALITY_CALL`` as the optimisation
    goal, ``IMPRESSIONS`` and ``CALL_NOW``. The ODAX mapping lists the same
    pair under traffic, with no promoted object.

    ``PHONE_CALL`` is **not** in the ad set reference's own
    ``destination_type`` enum, which stops at ``IMAGINE``. Two Meta pages
    that agree with each other beat one that disagrees with both."""
    for preset in every_preset():
        if preset.goal != "calls":
            continue
        assert preset.objective == "OUTCOME_TRAFFIC", preset.key
        assert preset.optimization_goal == "QUALITY_CALL", preset.key
        assert preset.billing_event == "IMPRESSIONS", preset.key
        assert preset.destination_type == "PHONE_CALL", preset.key
        assert preset.call_to_action == "CALL_NOW", preset.key


def test_every_calls_preset_says_the_tap_dials() -> None:
    """``destination_type`` says which of the objective's destinations was
    picked; ``sends_to`` says what the launch sequence has to build. Only
    the second can be asked "does this goal need a phone number", because
    the first is blank on two of the five goals now open."""
    for preset in every_preset():
        if preset.goal == "calls":
            assert preset.sends_to == "phone", preset.key
            assert preset.needs_phone is True, preset.key


def test_a_call_goal_needs_neither_a_form_nor_an_address() -> None:
    """Which is why it costs no new step. The link stays the formality it
    is on a lead ad - Meta's own example leaves the business page there -
    and the one object the rollback cannot remove is never created."""
    for preset in every_preset():
        if preset.needs_phone:
            assert preset.needs_lead_form is False, preset.key
            assert preset.needs_link is False, preset.key
            assert preset.opens_chat is False, preset.key


def test_the_awareness_preset_names_meta_s_word_for_no_button() -> None:
    """A ``LEARN_MORE`` here would not be cosmetic: the creative's link
    falls back to this deployment's front page for any goal that needs no
    address, so an awareness ad bought on impressions would carry a working
    button to our own site."""
    for preset in every_preset():
        if preset.sends_to == "nothing":
            assert preset.call_to_action == "NO_BUTTON", preset.key
            assert preset.shows_a_button is False, preset.key


def test_the_awareness_preset_carries_the_words_meta_names() -> None:
    """ODAX row: ``BRAND_AWARENESS`` becomes ``OUTCOME_AWARENESS`` with
    ``AD_RECALL_LIFT``, no destination type at all, and the page named in
    ``promoted_object``. The last of those is not the preset's to give -
    ``core/targeting`` has never heard of a page id - and is pinned in
    ``tests/apps/ads/test_launch_calls.py``."""
    for preset in every_preset():
        if preset.goal != "awareness":
            continue
        assert preset.objective == "OUTCOME_AWARENESS", preset.key
        assert preset.optimization_goal == "AD_RECALL_LIFT", preset.key
        assert preset.billing_event == "IMPRESSIONS", preset.key
        assert preset.destination_type == "", preset.key


def test_a_goal_that_sends_nobody_anywhere_may_not_name_a_button(
    tmp_path: Path,
) -> None:
    """Refused rather than corrected. A preset reading ``LEARN_MORE``
    beside ``sends_to: nothing`` is a sentence somebody will believe."""
    _write(
        tmp_path,
        """
provider: meta
category: cafe
label: Kafe
version: "1"
targeting_base:
  geo_locations: {countries: [UZ]}
presets:
  - goal: awareness
    label: Tanilish
    objective: OUTCOME_AWARENESS
    optimization_goal: AD_RECALL_LIFT
    billing_event: IMPRESSIONS
    sends_to: nothing
    call_to_action: LEARN_MORE
""",
    )
    with pytest.raises(CatalogError, match="NO_BUTTON"):
        PresetCatalog.from_directory(tmp_path)


def test_every_other_goal_keeps_a_real_button(tmp_path: Path) -> None:
    """The rule is one destination wide and not a general ban. A goal that
    does send somebody somewhere is free to name any button Meta has."""
    for preset in every_preset():
        if preset.sends_to != "nothing" and not preset.opens_chat:
            assert preset.call_to_action != "NO_BUTTON", preset.key
            assert preset.shows_a_button is True, preset.key


# --- The two answers, and how differently they are optional --------------
def test_a_call_launch_with_no_number_is_refused() -> None:
    """The gate, and it is the only thing between an advertiser and an ad
    that would have run. Meta accepts a call creative with no number: the
    button falls back to carrying the link."""
    with pytest.raises(PhoneNumberMissing):
        validate_launchable(built("calls", phone=""))


def test_an_awareness_launch_needs_no_destination_answer_at_all() -> None:
    """The only open goal that asks the wizard for nothing extra. No
    address, no greeting, no number - it is bought to be seen.

    The audience rules still apply, and that is the point of naming this
    test after the destination: five gates, and an awareness launch clears
    the two new ones by having nowhere to send anybody rather than by
    being exempt from anything."""
    validate_launchable(built("awareness", phone=""))


def test_a_number_on_a_goal_that_does_not_dial_is_carried_and_not_used() -> None:
    """The answers are what the wizard collected, not a set assembled per
    goal - the same bargain the chat channel makes. What keeps it out of
    the ad is ``needs_phone``, one layer up."""
    lead = built("leads", phone=E164)

    assert lead.phone_number == E164
    assert lead.needs_phone is False


def test_the_two_missing_answers_stay_two_different_failures() -> None:
    """A website goal with no address and a call goal with no number are
    both refused, and by different exceptions - because the screens that
    fix them say different words and point at different boxes."""
    with pytest.raises(DestinationLinkMissing):
        validate_launchable(built("traffic", phone=E164, category="ecommerce"))
    with pytest.raises(PhoneNumberMissing):
        validate_launchable(built("calls", phone=""))


def test_the_built_spec_carries_the_number_straight_through() -> None:
    """No fallback anywhere in the builder. The business profile has a
    phone column and substituting it here would dial a telephone nobody
    was told would ring."""
    assert built("calls", phone=E164).phone_number == E164
    assert built("calls", phone="").phone_number == ""


# --- Turning what was typed into something dialable ----------------------
def test_a_bare_local_number_needs_the_business_s_country() -> None:
    assert dialable(raw=TYPED, region="UZ") == E164


def test_a_number_written_with_a_plus_needs_no_country_at_all() -> None:
    """Which is why an empty region is not an error: a number that carries
    its own country code parses the same whatever is passed."""
    assert dialable(raw=E164, region="") == E164


def test_a_number_nobody_can_dial_comes_back_empty() -> None:
    """Empty rather than raising, like the lead pipeline this shares its
    parser with. The form is what turns empty into a sentence."""
    assert dialable(raw="12345", region="UZ") == ""
    assert dialable(raw="", region="UZ") == ""
    assert dialable(raw="salom", region="UZ") == ""


def test_the_stored_form_is_the_same_one_leads_are_stored_in() -> None:
    """One spelling of E.164 in this product. A number we dial and a
    number a customer left have to mean the same thing."""
    from core.leads.phone import to_e164

    assert dialable(raw=TYPED, region="UZ") == to_e164(raw=TYPED, region="UZ")


# --- Meta's country rule -------------------------------------------------
def test_a_number_from_the_audience_s_own_country_is_local() -> None:
    assert is_local(number=E164, region="UZ") is True


def test_a_number_from_somewhere_else_is_not() -> None:
    """Meta: *"The phone number included in Call to Action must be from the
    same country as the target audience."* Stated as a limitation rather
    than as an error code, which is the shape of rule that is enforced by
    nobody and paid for by the advertiser."""
    assert is_local(number=FOREIGN, region="UZ") is False


def test_an_unknown_country_is_permission_to_carry_on() -> None:
    """Twice over: a profile that never named a country, and a number no
    single country claims. Neither is evidence of a mismatch, and refusing
    a launch over a question nobody could answer is the more expensive
    mistake."""
    assert is_local(number=E164, region="") is True
    assert is_local(number="not a number", region="UZ") is True


def test_the_country_is_read_off_the_number_and_never_written_down() -> None:
    assert region_of(E164) == "UZ"
    assert region_of(FOREIGN) == "RU"
    assert region_of("nonsense") == ""


# --- The two new shapes, in the domain's own words -----------------------
def test_needs_phone_is_one_destination_and_not_a_family() -> None:
    for destination in ("form", "website", "chat", "store", "nothing"):
        assert needs_phone(destination) is False
    assert needs_phone("phone") is True


def test_shows_a_button_is_false_for_exactly_one_destination() -> None:
    for destination in ("form", "website", "chat", "store", "phone"):
        assert shows_a_button(destination) is True
    assert shows_a_button("nothing") is False
