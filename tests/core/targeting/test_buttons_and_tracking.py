"""The word on the button, and what the advert appends to the address.

Both are answers the catalogue has a default for and the owner may
override, and both are refused rather than sent when the override is one
the provider would not take - because both refusals arrive at the end of
the launch sequence, with a campaign, an ad set and an upload already made.
"""

from adskit import MinorUnits

from core.targeting import (
    BUTTONS,
    DEFAULT_TAGS,
    FIXED_BUTTONS,
    BuiltTargeting,
    BusinessProfile,
    ConversionSource,
    OnboardingAnswers,
    PresetCatalog,
    build,
    button,
    buttons_for,
    clean_tags,
    fallback,
    tags_are_usable,
)
from core.targeting.presets import CATALOG_DIR

PROVIDER = "meta"
CATALOG = PresetCatalog.from_directory(CATALOG_DIR)


def built(goal: str, **answers: str) -> BuiltTargeting:
    return build(
        provider=PROVIDER,
        answers=OnboardingAnswers(
            category="services",
            goal=goal,
            daily_budget_minor=MinorUnits(5000),
            **answers,
        ),
        business=BusinessProfile(name="Osh", category="services", country_code="UZ"),
        catalog=CATALOG,
        currency="USD",
        geo=fallback(country_code="UZ"),
        conversion=ConversionSource(external_id="777"),
        link="https://osh.uz",
        phone="+998901234567",
    )


# --- The buttons ----------------------------------------------------------
def test_no_word_is_offered_twice_for_one_destination() -> None:
    for (_provider, _sends_to), rows in BUTTONS.items():
        keys = [row.key for row in rows]
        assert len(keys) == len(set(keys))


def test_the_provider_names_are_its_screen_words_not_its_api_words() -> None:
    """Drawn beside the owner's words, so never ``LEARN_MORE``."""
    spelled_like_the_api = {
        row.key
        for rows in BUTTONS.values()
        for row in rows
        if "_" in row.provider_label or row.provider_label.isupper()
    }

    assert spelled_like_the_api == set()


def test_an_advert_that_dials_has_nothing_to_choose() -> None:
    """One word, so a list would be a step rather than a choice."""
    assert buttons_for(provider=PROVIDER, sends_to="phone") == ()
    assert FIXED_BUTTONS["phone"] == "CALL_NOW"


def test_a_word_from_another_destination_is_not_this_ones() -> None:
    assert button(provider=PROVIDER, sends_to="form", key="SEE_MENU") is None
    assert button(provider=PROVIDER, sends_to="website", key="SEE_MENU") is not None


# --- What a choice builds -------------------------------------------------
def test_nobody_choosing_keeps_the_catalogues_word() -> None:
    assert built("traffic").call_to_action == "LEARN_MORE"


def test_a_chosen_word_reaches_the_advert() -> None:
    assert (
        built("traffic", call_to_action="BOOK_TRAVEL").call_to_action == "BOOK_TRAVEL"
    )


def test_a_word_this_advert_may_not_carry_changes_nothing() -> None:
    """The provider refuses it on the last call of the sequence."""
    assert built("leads", call_to_action="SEE_MENU").call_to_action == "SIGN_UP"


def test_a_dialled_advert_keeps_its_one_word() -> None:
    assert built("calls", call_to_action="LEARN_MORE").call_to_action == "CALL_NOW"


# --- The tracking query ---------------------------------------------------
def test_a_pasted_query_loses_the_punctuation_that_joins_it() -> None:
    """The provider adds the ``?`` or the ``&``; a second one breaks the tail."""
    assert (
        clean_tags("?utm_source=fb&utm_medium=cpc&") == "utm_source=fb&utm_medium=cpc"
    )


def test_a_query_the_provider_could_not_append_is_not_usable() -> None:
    assert tags_are_usable("utm_source=fb?utm_medium=cpc") is False
    assert tags_are_usable("utm source=fb") is False
    assert tags_are_usable("=nothing") is False


def test_no_query_at_all_is_usable() -> None:
    """Which is what every campaign built before this question existed has."""
    assert tags_are_usable("") is True


def test_a_website_advert_carries_the_tags() -> None:
    spec = built("traffic", url_tags=DEFAULT_TAGS)

    assert spec.url_tags == DEFAULT_TAGS
    assert "{{campaign.name}}" in spec.url_tags


def test_a_form_advert_carries_none() -> None:
    """Its link is a formality the provider never follows."""
    assert built("leads", url_tags=DEFAULT_TAGS).url_tags == ""


def test_a_query_that_could_not_be_appended_is_dropped() -> None:
    assert built("traffic", url_tags="utm source=fb").url_tags == ""
