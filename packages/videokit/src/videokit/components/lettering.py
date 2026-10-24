"""Each text of a component at the size it fits its box at."""

from dataclasses import dataclass, field
from typing import Any, Final

from videokit.components.registry import Component
from videokit.fit import fitted_all, fitted_px, packed
from videokit.models import CONTACT_JOIN, Brand

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
