"""Where each answer on a form ended up, and which of them ended up nowhere."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from core.leads.normalise import ANSWER_KEYS, NAME_PARTS

_RENAMED: Final[dict[str, str]] = {"phone": "phone_e164"}

DESTINATIONS: Final[dict[str, str]] = {
    key: _RENAMED.get(column, column)
    for column, keys in ANSWER_KEYS.items()
    for key in keys
} | {part: "full_name" for part in NAME_PARTS}

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
    column: str = ""
    filled: bool = False

    @property
    def lost(self) -> bool:
        """A standard answer that arrived and did not get stored."""
        return bool(self.column) and not self.filled


def columns_of(source: Any) -> dict[str, str]:
    """The four stored values, off a normalised lead or off a saved row."""
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
    """The standard columns nothing filled, in screen order."""
    return tuple(column for column in STANDARD_COLUMNS if not stored.get(column, ""))
