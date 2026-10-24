"""Naming one slice of a segmented day.

One character of logic, and a test file anyway. The separator is written
into a column that is part of a unique key: a row joined one way and a row
joined another way are two rows where there should be one, and the symptom
is a segment whose spend is half what the provider says. Locking the format
here is what stops the second caller inventing it again.

No Django and no database - this is a string and its two halves.
"""

import pytest

from core.metrics import join_segment, split_segment


def test_the_stored_shape_is_parts_joined_by_a_pipe() -> None:
    """The literal, written down once so the rest can use the function."""
    assert join_segment("25-34", "female") == "25-34|female"
    assert join_segment("instagram", "feed") == "instagram|feed"


def test_a_one_dimensional_cut_is_just_its_value() -> None:
    """A device or region breakdown has one part and no separator."""
    assert join_segment("mobile_app") == "mobile_app"


def test_what_was_joined_comes_back_apart() -> None:
    assert split_segment(join_segment("65+", "male")) == ("65+", "male")
    assert split_segment("mobile_app") == ("mobile_app",)


def test_a_missing_half_is_named_rather_than_left_empty() -> None:
    """``25-34|`` and ``|female`` would both read as "we do not know".

    The provider's own word for it is ``unknown``, so a blank becomes that
    - otherwise two rows meaning the same thing sit under two different
    keys and neither adds up.
    """
    assert join_segment("25-34", "") == "25-34|unknown"
    assert join_segment("  ", "female") == "unknown|female"


def test_surrounding_space_does_not_make_a_second_row() -> None:
    assert join_segment(" 25-34 ", "female") == join_segment("25-34", "female")


def test_a_part_that_contains_the_separator_is_refused() -> None:
    """The one way this could corrupt a key silently.

    No value Meta sends today contains a pipe. A cut nobody has added yet
    might - a region name, a custom label - and the failure would be a
    value that splits into the wrong parts on the way back out, which
    nothing downstream could detect.
    """
    with pytest.raises(ValueError, match="may not contain"):
        join_segment("Tashkent|City", "female")


def test_a_segment_with_no_parts_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one part"):
        join_segment()
