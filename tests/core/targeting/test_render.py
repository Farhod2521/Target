"""Filling the holes in a preset, and refusing to leave one open.

A half-rendered spec is the failure worth engineering against. It is
accepted by nobody, but it fails at the provider rather than here, hours
later, with a message about a field the owner never saw.
"""

from dataclasses import dataclass

import pytest

from core.targeting.exceptions import CatalogError, UnfilledTemplate
from core.targeting.render import render


@dataclass(frozen=True)
class Source:
    age_min: int | None = 25
    city: str = "Tashkent"
    locales: tuple[int, ...] = (67, 26)
    genders: tuple[int, ...] = ()
    nothing: str = ""


def _render(node: object, **defaults: object) -> object:
    return render(node, sources={"answers": Source()}, defaults=defaults)


def test_a_lone_placeholder_keeps_the_value_s_type() -> None:
    """``age_min`` has to arrive as a number. The provider rejects "25"."""
    assert _render("{answers.age_min}") == 25


def test_a_placeholder_inside_a_sentence_becomes_text() -> None:
    assert _render("{answers.city} shahri") == "Tashkent shahri"


def test_a_tuple_becomes_a_list() -> None:
    """The spec is on its way into JSON, which has no tuples."""
    assert _render("{answers.locales}") == [67, 26]


def test_nested_structures_are_walked() -> None:
    node = {"geo": {"locations": [{"city": "{answers.city}"}]}}

    assert _render(node) == {"geo": {"locations": [{"city": "Tashkent"}]}}


def test_values_that_are_not_strings_pass_through() -> None:
    assert _render({"radius": 5, "on": True, "off": None}) == {
        "radius": 5,
        "on": True,
        "off": None,
    }


def test_an_unanswered_field_falls_back_to_the_preset_default() -> None:
    node = render(
        "{answers.age_min}",
        sources={"answers": Source(age_min=None)},
        defaults={"age_min": 30},
    )

    assert node == 30


def test_an_empty_string_counts_as_unanswered() -> None:
    assert _render("{answers.nothing}", nothing="filled") == "filled"


def test_an_empty_tuple_is_an_answer_and_not_a_gap() -> None:
    """``genders = ()`` means everyone. A default here would overrule it."""
    assert _render("{answers.genders}", genders=[1]) == []


def test_no_value_and_no_default_names_the_placeholder() -> None:
    with pytest.raises(UnfilledTemplate) as caught:
        render(
            {"targeting": {"age_min": "{answers.age_min}"}},
            sources={"answers": Source(age_min=None)},
            defaults={},
        )

    assert caught.value.placeholder == "answers.age_min"
    assert caught.value.path == "targeting.age_min"


def test_an_unknown_source_is_a_catalogue_bug() -> None:
    """A third source would let a YAML file reach whatever the caller held."""
    with pytest.raises(CatalogError) as caught:
        _render({"city": "{secrets.token}"})

    assert "secrets.token" in str(caught.value)


def test_an_unknown_field_names_the_field() -> None:
    with pytest.raises(CatalogError) as caught:
        _render({"city": "{answers.postcode}"})

    assert "postcode" in str(caught.value)


def test_a_mis_cased_placeholder_is_caught_rather_than_shipped() -> None:
    """It does not match, so it survives - which is exactly the danger."""
    with pytest.raises(UnfilledTemplate):
        _render({"city": "{Answers.city}"})


def test_an_unclosed_brace_is_caught_too() -> None:
    with pytest.raises(UnfilledTemplate):
        _render({"city": "{answers.city"})


def test_the_error_path_points_at_the_field_inside_a_list() -> None:
    with pytest.raises(UnfilledTemplate) as caught:
        _render({"locations": [{"city": "{answers.city"}]})

    assert caught.value.path == "locations[0].city"
