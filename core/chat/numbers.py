"""What counts as a figure, and what it looks like with the separators gone.

One tokeniser, used twice and on purpose: it builds the set of figures the
context supplied, and it scans what Claude wrote. Two tokenisers would be
two opinions about where a number starts, and the day they disagree is the
day a real figure is masked or an invented one is let through.

The comparison is on digits alone. A figure is rendered by Django in the
reader's locale - "15 000" in Uzbek and Russian, "15,000" in English - and
the same amount must match itself whichever screen produced it.
"""

import re
from typing import Final

# The spaces a thousands separator can be. Written as escapes rather than
# typed: a no-break space is invisible in a diff, and the narrow one is
# what Django's number formatting actually emits.
GAPS: Final = " \u00a0\u202f"

# A run of digits, plus the separators a rendered figure carries *inside*
# it. Thousands are split by a space of some kind; a comma or a full stop
# only continues the number when a digit follows it directly, so the stop
# ending a sentence is not swallowed and "1, 2, 3" stays three figures.
FIGURE: Final = re.compile(rf"\d+(?:[{GAPS}]\d{{3}})*(?:[.,]\d+)?")

# Everything that is not a digit. Separators differ by locale and none of
# them changes which amount is meant.
NON_DIGIT: Final = re.compile(r"\D")

# A figure that ends a chunk may not have ended: "15" arriving now can
# become "15 000" next time, and a complete number can still be followed
# by a per-cent sign. Anything matching this at the tail is held back.
UNFINISHED: Final = re.compile(rf"\d[\d{GAPS},.]*$")


def canonical(token: str) -> str:
    """The figure as digits only, which is how two of them are compared."""
    return NON_DIGIT.sub("", token)


def figures_in(text: str) -> frozenset[str]:
    """Every figure in ``text``, canonical.

    Used on the context to say what may be quoted, and on the answer to
    say what was. The set is deliberately not ordered or counted: the
    question is only ever "did this number come from somewhere real".
    """
    return frozenset(
        digits
        for match in FIGURE.finditer(text)
        if (digits := canonical(match.group(0)))
    )
