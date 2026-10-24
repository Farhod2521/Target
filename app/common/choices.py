"""Django's TextChoices manners for the ported StrEnums.

``Kind.X.label``, ``Kind.values``, ``Kind.choices`` and ``Kind.labels`` keep
working. Labels live beside each enum in its constants module as
``<SNAKE_NAME>_LABELS``, which is where tools/port_constants.py writes them.
"""

import re
import sys
from enum import EnumType, StrEnum
from typing import Any

_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def _labels(cls: Any) -> dict[Any, str]:
    module = sys.modules.get(cls.__module__)
    name = _CAMEL.sub("_", cls.__name__).upper() + "_LABELS"
    return getattr(module, name, None) or {}


class ChoicesMeta(EnumType):
    @property
    def values(cls) -> list[str]:
        return [member.value for member in cls]  # type: ignore[attr-defined]

    @property
    def labels(cls) -> list[str]:
        return [member.label for member in cls]  # type: ignore[attr-defined]

    @property
    def choices(cls) -> list[tuple[str, str]]:
        return [(member.value, member.label) for member in cls]  # type: ignore[attr-defined]


class Choices(StrEnum, metaclass=ChoicesMeta):
    @property
    def label(self) -> str:
        found = _labels(type(self))
        return str(found.get(self, self.value.replace("_", " ").capitalize()))
