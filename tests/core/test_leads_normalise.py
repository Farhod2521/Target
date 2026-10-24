"""Reading a lead form's answer sheet, and a phone number off it.

The four columns every platform names the same way. Everything else stays
in the raw payload, because the questions are the advertiser's and no fixed
set of columns can hold them.
"""

import pytest

from core.leads import normalise, to_e164


def answers(**pairs: str) -> list[dict]:
    return [{"name": key, "values": [value]} for key, value in pairs.items()]


# --- The four columns ----------------------------------------------------
def test_the_standard_answers_are_read_out() -> None:
    found = normalise(
        field_data=answers(
            full_name="Aziz Karimov",
            phone_number="90 123 45 67",
            email="Aziz@Example.COM",
            city="Toshkent",
        ),
        region="UZ",
    )

    assert found.full_name == "Aziz Karimov"
    assert found.phone_e164 == "+998901234567"
    # Lowercased, because an address is the same address either way and a
    # duplicate check that is case-sensitive finds none.
    assert found.email == "aziz@example.com"
    assert found.city == "Toshkent"


def test_a_form_asking_for_two_name_parts_still_produces_one_name() -> None:
    """A screen shows one name and an export writes one column. The parts
    are still in the raw answers for anybody who needs them apart."""
    found = normalise(
        field_data=answers(first_name="Aziz", last_name="Karimov"), region="UZ"
    )

    assert found.full_name == "Aziz Karimov"


def test_a_full_name_wins_over_the_parts() -> None:
    found = normalise(
        field_data=answers(
            full_name="Aziz Karimov", first_name="Wrong", last_name="Also wrong"
        ),
        region="UZ",
    )

    assert found.full_name == "Aziz Karimov"


def test_a_question_the_form_did_not_ask_leaves_its_column_empty() -> None:
    found = normalise(field_data=answers(full_name="Aziz"), region="UZ")

    assert found.phone_e164 == ""
    assert found.email == ""
    assert found.city == ""


def test_a_custom_question_is_ignored_here_and_kept_elsewhere() -> None:
    """Custom keys are generated per form and can be anything. They are
    read by whoever knows which form they belong to."""
    found = normalise(field_data=answers(q3="12:00", full_name="Aziz"), region="UZ")

    assert found.full_name == "Aziz"


def test_an_unreadable_phone_costs_the_column_and_not_the_lead() -> None:
    """Losing a lead because somebody mistyped a digit would be losing the
    thing the product exists to collect."""
    found = normalise(
        field_data=answers(full_name="Aziz", phone_number="nonsense"), region="UZ"
    )

    assert found.phone_e164 == ""
    assert found.full_name == "Aziz"


def test_an_empty_answer_sheet_is_not_a_failure() -> None:
    assert normalise(field_data=[], region="") == normalise(field_data=[], region="UZ")


# --- The phone number ----------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "region", "expected"),
    [
        pytest.param("90 123 45 67", "UZ", "+998901234567", id="local"),
        pytest.param(
            "+998 90 123-45-67", "", "+998901234567", id="already-international"
        ),
        pytest.param("8 (901) 234-56-78", "RU", "+79012345678", id="another-country"),
        pytest.param("+1 415 555 2671", "", "+14155552671", id="no-region-needed"),
        # A number the right length with a prefix no operator uses. It
        # passes every check we have and fails when somebody dials it.
        pytest.param("+998 00 000 00 00", "", "", id="possible-but-invalid"),
        pytest.param("", "UZ", "", id="empty"),
        pytest.param("nonsense", "UZ", "", id="not-a-number"),
    ],
)
def test_a_number_is_stored_the_same_way_whatever_country_it_is_from(
    raw: str, region: str, expected: str
) -> None:
    """E.164 is the only form that means the same thing in two countries,
    and no country is privileged - the region comes from the profile."""
    assert to_e164(raw=raw, region=region) == expected


def test_the_region_is_only_consulted_when_the_number_lacks_one() -> None:
    """A form that collected an international number needs no help, which
    is why an empty region is not an error."""
    assert to_e164(raw="+998901234567", region="RU") == "+998901234567"


@pytest.mark.parametrize(
    ("stored", "shown"),
    [
        ("+998712223344", "+998 71 222 33 44"),
        ("+998901112233", "+998 90 111 22 33"),
        ("+12025550123", "+1 202 555 0123"),
        ("not a number", "not a number"),
    ],
)
def test_a_phone_is_shown_grouped_with_spaces(stored: str, shown: str) -> None:
    from core.leads.phone import for_display

    assert for_display(stored) == shown
