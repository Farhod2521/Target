"""The icons components draw: twenty, one style, one colour.

Each is an inline SVG in ``videokit/icons/<name>.svg`` on a 24-unit grid,
drawn in ``currentColor`` - a component colours it with one of the
brand's tokens (``color: var(--accent)``) and sizes it with its box. The
renderer draws inline SVG and moves it (docs/montage_spike2.md).

A component takes one as a prop of type ``icon`` (see the registry):
the planner picks a name from :data:`ICONS`, and the template writes the
drawing where it says ``{{{ name }}}``.
"""

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
