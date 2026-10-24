"""Which graphics can never be on screen together, worked out from their
manifests, for the planner to be told rather than to find out."""

from collections import defaultdict
from typing import Final

from videokit.components import Component, component, components
from videokit.layout import zones_meet

_NAME_BAR: Final = "lower_third"


def clashes() -> dict[str, frozenset[str]]:
    """Each graphic a planner may place (and the name bar) with every one it
    can never share the screen with - itself included, when two of it at
    once would clash."""
    shown = [
        item
        for item in components().values()
        if item.placement == "planner" or item.name == _NAME_BAR
    ]
    return {
        item.name: frozenset(o.name for o in shown if _clash(item, o)) for item in shown
    }


def conflicts_text() -> str:
    """:func:`clashes` as lines for the prompt, one per band and kind of
    graphic: what can be up while one of them is."""
    found = clashes()
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for name in found:
        item = component(name)
        groups[(item.zones[0], item.layer)].append(name)
    lines = []
    for (zone, layer), names in sorted(groups.items()):
        own = sorted(names)
        others = sorted(set().union(*(found[n] for n in own)) - set(own))
        twice = any(found[n] & set(own) for n in own)
        said = []
        if twice:
            said.append("a second one of " + ("these" if len(own) > 1 else "it"))
        if others:
            said.append(_listed(others))
        kind = " (a decoration: it gives way)" if layer == "decor" else ""
        lines.append(
            f"- {zone}{kind} - {_listed(own)}: never with {' or '.join(said)}."
        )
    return "\n".join(lines)


def _clash(one: Component, other: Component) -> bool:
    front = one.layer == "front" or other.layer == "front"
    return bool(front and zones_meet(one.zones[0], other.zones[0]))


def _listed(names: list[str]) -> str:
    return ", ".join(f"`{name}`" for name in names)
