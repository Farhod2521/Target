"""Where each answer on a form ended up, and which of them ended up nowhere.

The question a first live test asks: the person filled the form in, so why
is that column empty. There are three ways an answer can land and they are
not degrees of the same thing.

* It filled the column it was supposed to fill. The working case.
* It has a column and the column is empty. A **normalisation failure** -
  Meta accepted something ``to_e164`` could not read - and the only one of
  the three worth chasing.
* It has no column at all, by design. A question the advertiser invented
  has nowhere standard to go and is kept whole in ``answers`` and in the
  raw payload, which is not a gap.

Here rather than in the trace that prints it, because two callers need the
same answer from two different starting points: the import, which holds a
provider DTO and a freshly normalised lead, and the report, which holds a
row that was written days ago. A second copy of this table would be a
second copy that disagrees.

Django-free, like everything else in ``core``: what goes in is a list of
answers and the four values that were stored, and what comes out says
which is which.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from core.leads.normalise import ANSWER_KEYS, NAME_PARTS

# The one standard key whose column is not called what the key is called.
# Meta answers ``phone_number``; the column holds an E.164 number and says
# so, because a column called ``phone`` would be a column somebody puts
# "90 123 45 67" in.
_RENAMED: Final[dict[str, str]] = {"phone": "phone_e164"}

# Which stored column each key Meta may use fills. Derived from
# ``ANSWER_KEYS`` rather than restated: that is what ``normalise`` actually
# reads, so a key added there appears here without anybody remembering to
# come back - and a table that disagreed with the code would be worse than
# no table at all.
DESTINATIONS: Final[dict[str, str]] = {
    key: _RENAMED.get(column, column)
    for column, keys in ANSWER_KEYS.items()
    for key in keys
} | {part: "full_name" for part in NAME_PARTS}

# The four a lead screen shows, in the order it shows them.
STANDARD_COLUMNS: Final[tuple[str, ...]] = (
    "full_name",
    "phone_e164",
    "email",
    "city",
)


@dataclass(frozen=True, slots=True)
class Landing:
    """One answer, and what became of it."""

    key: str
    values: tuple[str, ...]
    # Empty when this key has no standard column, which is the ordinary
    # case for a question somebody wrote themselves.
    column: str = ""
    # Whether that column ended up with something in it. Meaningless when
    # there is no column, and never read in that case.
    filled: bool = False

    @property
    def lost(self) -> bool:
        """A standard answer that arrived and did not get stored."""
        return bool(self.column) and not self.filled


def columns_of(source: Any) -> dict[str, str]:
    """The four stored values, off a normalised lead or off a saved row.

    Both have the same four attributes, which is not a coincidence: the row
    is written from the normalised lead field by field.
    """
    return {
        column: str(getattr(source, column, "") or "") for column in STANDARD_COLUMNS
    }


def landings(
    *, field_data: Iterable[Mapping[str, Any]], stored: Mapping[str, str]
) -> tuple[Landing, ...]:
    """Every answer the provider sent, in the order it sent them."""
    found = []
    for item in field_data:
        key = str(item.get("name", ""))
        column = DESTINATIONS.get(key, "")
        found.append(
            Landing(
                key=key,
                values=tuple(str(value) for value in item.get("values") or ()),
                column=column,
                filled=bool(stored.get(column, "")),
            )
        )
    return tuple(found)


def empty_columns(*, stored: Mapping[str, str]) -> tuple[str, ...]:
    """The standard columns nothing filled, in screen order.

    Empty is not automatically a fault - most forms ask for two of the four
    - so this is read beside :attr:`Landing.lost`, which is the half that
    says whether an answer for it actually arrived.
    """
    return tuple(column for column in STANDARD_COLUMNS if not stored.get(column, ""))
