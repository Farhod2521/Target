"""Each text of a component at the size it fits its box at.

A component's manifest names the box every text is written in
(``texts``); here the text the clip will actually show is measured
(:mod:`videokit.fit`) and given its size as one CSS rule per text. A
list (the chips) takes one size for all its items, so they stay alike.

**Contacts** are laid out rather than shrunk: the handle and the phone
share a line while they fit on one at the box's smallest size, and go
onto lines of their own when they do not. A phone number is never
broken.

What fits nowhere is named in ``overflow``; the clip is still drawn (at
the smallest size), and :mod:`videokit.preflight` stops the montage
before it reaches the renderer.
"""

from dataclasses import dataclass, field
from typing import Any, Final

from videokit.components.registry import Component
from videokit.fit import fitted_all, fitted_px, packed
from videokit.models import CONTACT_JOIN, Brand

# The value a component lists contacts in; filled here, not by the brand.
CONTACT_LINES: Final = "cta_contact_lines"


@dataclass(frozen=True, slots=True)
class Lettering:
    """The sizes a clip's texts are drawn at, and what did not fit."""

    sizes: dict[str, int] = field(default_factory=dict)
    values: dict[str, Any] = field(default_factory=dict)
    overflow: tuple[str, ...] = ()

    def css(self, item: Component) -> str:
        boxes = dict(item.texts)
        return "".join(
            f"{boxes[name].selector}{{font-size:{px}px}}"
            for name, px in self.sizes.items()
        )


def lettering(item: Component, values: dict[str, Any], *, brand: Brand) -> Lettering:
    """``item``'s texts measured, with ``values`` as the template sees them."""
    sizes: dict[str, int] = {}
    extra: dict[str, Any] = {}
    overflow: list[str] = []
    for name, box in item.texts:
        if name == CONTACT_LINES:
            parts = [p for p in brand.cta_contacts.split(CONTACT_JOIN) if p]
            if not parts:
                continue
            found = packed(parts, box, preset=brand.font, joiner=CONTACT_JOIN)
            if found is None:
                overflow.append(name)
                sizes[name], extra[name] = box.min_px, parts
            else:
                sizes[name], extra[name] = found[0], list(found[1])
            continue
        value = values.get(name)
        if not value:
            continue
        if isinstance(value, list):
            px = fitted_all([str(v) for v in value], box, preset=brand.font)
        else:
            px = fitted_px(str(value), box, preset=brand.font)
        if px is None:
            overflow.append(name)
            px = box.min_px
        sizes[name] = px
    return Lettering(sizes=sizes, values=extra, overflow=tuple(overflow))
