"""The icons components draw: twenty, one style, one colour."""

from functools import cache
from pathlib import Path
from typing import Final, Literal, get_args

IconName = Literal[
    "check", "heart", "star", "sparkle", "rocket", "globe", "pin", "people",
    "target", "shield", "medal", "fire", "gift", "clock", "money", "phone",
    "cart", "truck", "percent", "arrow",
]  # fmt: skip
ICONS: Final[tuple[IconName, ...]] = get_args(IconName)

_FOLDER: Final = Path(__file__).parent / "icons"


@cache
def icon_svg(name: IconName) -> str:
    """The icon's drawing, as markup to write into a template."""
    return (_FOLDER / f"{name}.svg").read_text(encoding="utf-8").strip()
