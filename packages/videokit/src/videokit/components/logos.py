"""The size each component draws the logo at, as CSS.

Worked out by :mod:`videokit.logo_fit` from the copy the component shows:
tall enough for the logo's lettering to read, within the component's own
limits. The CSS follows the component's own, so it wins.
"""

from typing import Any

from videokit.logo_fit import (
    CARD_MAX,
    CARD_WITH_NAME,
    NAME_BAR_MAX_WIDTH,
    corner_size,
    drawn_size,
    name_bar_logo,
)


def logo_css(name: str, values: dict[str, Any]) -> str:
    """The rule sizing ``name``'s logo, from the values it is drawn with."""
    if name == "corner_logo":
        copy = (
            values["logo_on_dark"] if values.get("on_dark") else values["logo_on_light"]
        )
        size = corner_size(copy) if copy else None
        return f".c{{width:{size[0]}px;height:{size[1]}px}}" if size else ""
    if name == "lower_third" and values.get("logo_instead_of_name"):
        height = name_bar_logo(values["logo_instead_of_name"])
        if height:
            return f".solo{{height:{height}px;max-width:{NAME_BAR_MAX_WIDTH}px}}"
    if name == "end_card" and values.get("card_logo"):
        box = CARD_WITH_NAME if values.get("card_name") else CARD_MAX
        size = drawn_size(values["card_logo"], box)
        if size:
            return f".logo{{width:{size[0]}px;height:{size[1]}px}}"
    return ""
