"""The checks before a render that look at logos and buttons.

Apart from :mod:`videokit.preflight` only to keep each file short; the
problems are its own (:class:`videokit.preflight.Problem`).

- **logo_cut** - a logo copy on a plate whose mark reaches the plate's
  edge (:attr:`videokit.logo_fit.LogoCopy.on_plate_whole`).
- **logo_text** - a logo shown in place of the name (the corner, the name
  bar, the closing card) whose lettering would be drawn under
  :data:`videokit.logo_fit.MIN_TEXT_PX`.
- **tap_on_text** - a button's tap circle that, grown as far as its
  timeline grows it (:data:`TAP_GROW`), would reach the button's words.
"""

from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

from videokit.components import component
from videokit.components.render import brand_values
from videokit.logo_fit import (
    CARD_MAX,
    CARD_WITH_NAME,
    MIN_TEXT_PX,
    corner_size,
    drawn_size,
    logo_copy,
    name_bar_logo,
)
from videokit.models import ComponentUse, EditSpec

if TYPE_CHECKING:
    from videokit.preflight import Problem

# How far a tap circle grows as it fades (``scale`` in the timelines), and
# the gap it keeps from the words even then.
TAP_GROW: Final = 1.4
TAP_GAP: Final = 6


def logo_problems(spec: EditSpec) -> Iterator["Problem"]:
    """Every logo and button problem in ``spec``."""
    from videokit.preflight import Problem

    values = brand_values(spec.brand)
    for use in spec.components:
        for kind, note in _logo(use, values) + _tap(use):
            yield Problem(kind=kind, subject=use.name, at=use.start, note=note)  # type: ignore[arg-type]


def _logo(use: ComponentUse, values: dict[str, object]) -> list[tuple[str, str]]:
    shown: list[tuple[str, int | None]] = []
    if use.name == "corner_logo":
        copy = str(
            values["logo_on_dark" if use.props.get("on_dark") else "logo_on_light"]
        )
        size = corner_size(copy) if copy else None
        shown.append((copy, size[1] if size else 0))
    elif use.name == "lower_third":
        if solo := str(values["logo_instead_of_name"]):
            shown.append((solo, name_bar_logo(solo) or 0))
        if mark := str(values["logo_beside_name"]):
            shown.append((mark, None))
    elif use.name == "end_card" and (card := str(values["card_logo"])):
        box = CARD_WITH_NAME if values["card_name"] else CARD_MAX
        size = drawn_size(card, box)
        shown.append((card, None if values["card_name"] else (size[1] if size else 0)))
    problems = []
    for uri, height in shown:
        copy = logo_copy(uri)
        if copy is None:
            continue
        if not copy.on_plate_whole:
            problems.append(("logo_cut", "the mark reaches the plate's edge"))
        px = copy.text_px(height) if height is not None else None
        if px is not None and px < MIN_TEXT_PX:
            problems.append(
                ("logo_text", f"lettering {px:.0f}px under {MIN_TEXT_PX}px")
            )
    return problems


def _tap(use: ComponentUse) -> list[tuple[str, str]]:
    tap = component(use.name).tap
    if tap is None:
        return []
    radius, inset = tap
    if radius * TAP_GROW + TAP_GAP <= inset:
        return []
    return [("tap_on_text", f"a {radius}px circle grown {TAP_GROW}x reaches {inset}px")]
