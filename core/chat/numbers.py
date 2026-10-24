"""What counts as a figure, and what it looks like with the separators gone."""

import re
from typing import Final

GAPS: Final = " \u00a0\u202f"

FIGURE: Final = re.compile(rf"\d+(?:[{GAPS}]\d{{3}})*(?:[.,]\d+)?")

NON_DIGIT: Final = re.compile(r"\D")

UNFINISHED: Final = re.compile(rf"\d[\d{GAPS},.]*$")


def canonical(token: str) -> str:
    """The figure as digits only, which is how two of them are compared."""
    return NON_DIGIT.sub("", token)


def figures_in(text: str) -> frozenset[str]:
    """Every figure in ``text``, canonical."""
    return frozenset(
        digits
        for match in FIGURE.finditer(text)
        if (digits := canonical(match.group(0)))
    )
