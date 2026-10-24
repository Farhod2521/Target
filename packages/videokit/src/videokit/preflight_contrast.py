"""The check before a render that words over the footage can be read.

Apart from :mod:`videokit.preflight` only to keep each file short.
**low_contrast**: a headline or a subtitle line whose words, against how
light the footage behind them is (``backdrop``, measured on the stills
while they are up), fall under :data:`MIN_CONTRAST` - and that has no dark
backing (``scrim``) to make up for it. Words on a plate of their own (the
name bar, a button, a panel, the closing card) are not over footage.
"""

from collections.abc import Iterator
from typing import TYPE_CHECKING, Final

from videokit.colors import contrast_ratio
from videokit.karaoke import caption_colors
from videokit.models import EditSpec

if TYPE_CHECKING:
    from videokit.preflight import Problem

# Large, bold words read at 3:1 (WCAG's figure for large text).
MIN_CONTRAST: Final = 3.0
# The components whose words sit straight on the footage.
OVER_FOOTAGE: Final = frozenset(
    {"hook_title", "hook_counter", "headline_slam", "price_tag"}
)


def grey(light: float) -> str:
    """A grey as light as ``light`` (0-1), as ``#rrggbb``."""
    level = round(max(0.0, min(light, 1.0)) * 255)
    return f"#{level:02x}{level:02x}{level:02x}"


def needs_scrim(ink: str, light: float) -> bool:
    """Whether words in ``ink`` need a dark backing over footage this light."""
    return contrast_ratio(ink, grey(light)) < MIN_CONTRAST


def contrast_problems(spec: EditSpec) -> Iterator["Problem"]:
    """Every word over footage that cannot be read."""
    from videokit.preflight import Problem

    for use in spec.components:
        light = use.backdrop
        if use.name not in OVER_FOOTAGE or light is None or use.scrim:
            continue
        if needs_scrim(spec.brand.text, light):
            yield Problem(
                kind="low_contrast",
                subject=use.name,
                at=use.start,
                note=f"footage {light:.2f} light behind its words",
            )
    ink, _lit = caption_colors(spec.brand)
    for line in spec.captions:
        if (
            line.backdrop is not None
            and not line.scrim
            and needs_scrim(ink, line.backdrop)
        ):
            yield Problem(
                kind="low_contrast",
                subject="captions",
                at=line.start,
                note=f"footage {line.backdrop:.2f} light behind the line",
            )
