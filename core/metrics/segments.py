"""How one slice of a segmented day is named.

A breakdown row's identity is a pair of words - an age bucket and a gender,
a platform and a placement - and it is stored in one column rather than
two. The number of dimensions differs per cut: age and gender are two, a
device breakdown is one, and a placement-by-hour cut would be three. A
table with a column per possible dimension is a table that is mostly null.

So the parts are joined, and this module owns the joining. Not because the
rule is complicated - it is one character - but because a separator written
by hand in five places is a separator that is written differently in the
sixth, and the sixth is a row that never matches the row it was meant to
replace.

No Django and no provider here: this is a string and its two halves.
"""

from typing import Final

# What joins the parts of one segment: ``25-34|female``, ``instagram|feed``.
#
# A pipe because no provider value contains one. Meta's age buckets are
# digits with a hyphen or a plus, its genders and platforms are lowercase
# words, and its placements join words with underscores. A value that ever
# did contain one would silently split into the wrong parts, which is why
# :func:`join_segment` refuses it rather than trusting the survey above to
# stay true for a cut nobody has added yet.
SEPARATOR: Final = "|"

# What the provider sends when it could not attribute a row to any slice.
# Kept rather than dropped: a day whose segments fall short of its total is
# normal, and this is where the shortfall goes.
UNKNOWN: Final = "unknown"


def join_segment(*parts: str) -> str:
    """One stored value from the parts of a cut.

    Blank parts become ``unknown`` rather than an empty string, because an
    empty half would make ``25-34|`` and ``|female`` two different rows
    that both read as "we do not know" - and because the provider's own
    word for the same thing is already ``unknown``.
    """
    if not parts:
        raise ValueError("a segment needs at least one part")

    cleaned = []
    for part in parts:
        text = part.strip()
        if SEPARATOR in text:
            raise ValueError(f"a segment part may not contain {SEPARATOR!r}: {part!r}")
        cleaned.append(text or UNKNOWN)
    return SEPARATOR.join(cleaned)


def split_segment(value: str) -> tuple[str, ...]:
    """The parts back out, in the order they were joined.

    The inverse of :func:`join_segment` for anything that function wrote.
    A single-part value comes back as a one-tuple rather than a string, so
    that a caller reading a one-dimensional cut and a two-dimensional one
    is written the same way.
    """
    return tuple(value.split(SEPARATOR))
