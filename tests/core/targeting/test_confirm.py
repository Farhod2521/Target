"""Matching chosen names against what a provider recognised.

The rule under test throughout: a name the provider does not have is
dropped with a reason and never quietly swapped for something similar. A
silent substitution spends somebody's budget on an audience they did not
choose, and nothing on the screen would say so.
"""

from core.targeting import Interest
from core.targeting.confirm import (
    Found,
    apply_found,
    needs_lookup,
    retranslate,
    stand_in_room,
    stand_ins,
)

RESTAURANTS = Interest(label="Restoranlar", query="Restaurants")
BARBER = Interest(label="Sartaroshxona", query="sartaroshxona")
CONFIRMED = Interest(label="Kofe", query="Coffee", external_id="6003", audience_size=90)


def found(name: str, external_id: str = "6001", lower: int = 500_000) -> Found:
    return Found(
        name=name,
        external_id=external_id,
        audience_lower=lower,
        audience_upper=lower * 2,
    )


# --- What is worth asking about ------------------------------------------
def test_a_name_that_already_has_an_id_is_not_asked_about_again() -> None:
    """The cache doing its job: a returning advertiser's second campaign
    starts with its interests already confirmed."""
    assert needs_lookup((CONFIRMED, RESTAURANTS)) == ("Restaurants",)


def test_the_same_name_twice_is_one_question() -> None:
    twice = (RESTAURANTS, Interest(label="Restoran", query="restaurants"))

    assert needs_lookup(twice) == ("Restaurants",)


def test_a_blank_query_is_not_sent_to_a_provider() -> None:
    assert needs_lookup((Interest(label="  ", query="   "),)) == ()


def test_nothing_to_confirm_is_an_empty_tuple_not_a_call() -> None:
    assert needs_lookup((CONFIRMED,)) == ()


# --- Splitting the list --------------------------------------------------
def test_a_recognised_name_gains_an_id_and_a_size() -> None:
    result = apply_found((RESTAURANTS,), (found("Restaurants", "6003123", 900_000),))

    assert result.confirmed[0].external_id == "6003123"
    assert result.confirmed[0].audience_size == 900_000
    assert result.missing == ()


def test_the_providers_capitalisation_is_not_treated_as_a_miss() -> None:
    """ "coffee" goes out and "Coffee" comes back. Half of every list would
    be dropped if that counted as a different word."""
    result = apply_found((BARBER,), (found("Sartaroshxona"),))

    assert result.confirmed[0].external_id == "6001"
    assert result.missing == ()


def test_the_owner_keeps_reading_the_word_they_typed() -> None:
    """Meta files it under its own name. That is Meta's business, not the
    business of the person looking at their own screen."""
    result = apply_found((BARBER,), (found("Sartaroshxona"),))

    assert result.confirmed[0].label == "Sartaroshxona"


def test_a_name_nobody_recognised_lands_in_missing() -> None:
    result = apply_found((RESTAURANTS, BARBER), (found("Restaurants"),))

    assert [item.query for item in result.missing] == ["sartaroshxona"]


def test_already_confirmed_names_are_kept_apart_from_newly_confirmed() -> None:
    """So the caller caches only what it actually learned, and the screen
    can say "checked" without checking again."""
    result = apply_found((CONFIRMED, RESTAURANTS), (found("Restaurants"),))

    assert result.unchanged == (CONFIRMED,)
    assert [item.query for item in result.confirmed] == ["Restaurants"]
    assert len(result.all_confirmed) == 2


def test_an_unrelated_row_in_the_answer_confirms_nothing() -> None:
    """Providers answer lists. A row for a name nobody asked about must not
    attach itself to the nearest chosen interest."""
    result = apply_found((RESTAURANTS,), (found("Barbershop"),))

    assert result.confirmed == ()
    assert len(result.missing) == 1


def test_a_list_where_everything_failed_is_not_launchable() -> None:
    result = apply_found((RESTAURANTS, BARBER), ())

    assert result.is_launchable is False
    assert len(result.missing) == 2


def test_one_survivor_is_enough() -> None:
    """The product's floor: at least one confirmed interest."""
    result = apply_found((RESTAURANTS, BARBER), (found("Restaurants"),))

    assert result.is_launchable is True


# --- Second attempt ------------------------------------------------------
def test_a_translated_name_keeps_its_label_and_changes_its_query() -> None:
    """The whole feature in one assertion: the owner keeps their word, the
    provider is asked about a word it might have."""
    retried = retranslate((BARBER,), {"sartaroshxona": "Barbershop"})

    assert retried[0].label == "Sartaroshxona"
    assert retried[0].query == "Barbershop"


def test_a_name_with_no_translation_comes_back_unchanged() -> None:
    """Deciding it is unusable is the caller's job, done once."""
    retried = retranslate((BARBER,), {})

    assert retried == (BARBER,)


def test_translation_is_matched_case_insensitively_too() -> None:
    retried = retranslate((RESTAURANTS,), {"restaurants": "Restaurant"})

    assert retried[0].query == "Restaurant"


# --- Stand-ins -----------------------------------------------------------
HOTELS = Interest(label="Mehmonxonalar", query="Hotels", external_id="6010")
AIR = Interest(label="Aviachiptalar", query="Air travel", external_id="6011")
HAJJ = Interest(label="Haj", query="Hajj")


def test_a_confirmed_spare_takes_a_dropped_names_place() -> None:
    """The first confirmed one, in the proposal's own order. A spare the
    provider does not know either replaces nothing."""
    picked = stand_ins(kept=(CONFIRMED,), dropped=(BARBER,), spare=(HAJJ, HOTELS, AIR))

    assert picked == (HOTELS,)


def test_never_more_stand_ins_than_the_list_is_short_of() -> None:
    """Three kept and three dropped is one place left under the target."""
    kept = tuple(
        Interest(label=f"n{n}", query=f"q{n}", external_id=f"{n}") for n in range(3)
    )

    assert stand_in_room(kept=3, dropped=3) == 1
    assert stand_ins(
        kept=kept, dropped=(BARBER, RESTAURANTS, HAJJ), spare=(HOTELS, AIR)
    ) == (HOTELS,)


def test_a_list_that_lost_nothing_takes_no_stand_in() -> None:
    """Growing a list the provider accepted whole is a decision nobody made."""
    assert stand_in_room(kept=1, dropped=0) == 0
    assert stand_ins(kept=(CONFIRMED,), dropped=(), spare=(HOTELS,)) == ()


def test_a_spare_already_in_the_list_under_another_name_is_skipped() -> None:
    same = Interest(label="Qahva ichish", query="Coffee drinking", external_id="6003")

    assert stand_ins(kept=(CONFIRMED,), dropped=(BARBER,), spare=(same, HOTELS)) == (
        HOTELS,
    )
