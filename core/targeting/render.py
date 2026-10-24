"""Filling ``{business.city}`` and ``{answers.age_min}`` in a preset."""

import re
from collections.abc import Mapping
from typing import Any

from core.targeting.exceptions import CatalogError, UnfilledTemplate

PLACEHOLDER = re.compile(r"\{([a-z_]+)\.([a-z_][a-z_0-9]*)\}")


def render(
    node: Any,
    *,
    sources: Mapping[str, object],
    defaults: Mapping[str, Any],
    path: str = "",
) -> Any:
    """Walk a preset fragment, replacing every placeholder it contains."""
    if isinstance(node, dict):
        return {
            key: render(
                value, sources=sources, defaults=defaults, path=_join(path, str(key))
            )
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [
            render(value, sources=sources, defaults=defaults, path=f"{path}[{index}]")
            for index, value in enumerate(node)
        ]
    if isinstance(node, str):
        return _render_text(node, sources=sources, defaults=defaults, path=path)
    return node


def _render_text(
    text: str,
    *,
    sources: Mapping[str, object],
    defaults: Mapping[str, Any],
    path: str,
) -> Any:
    """One string. Returns a value when it is nothing but a placeholder."""
    alone = PLACEHOLDER.fullmatch(text)
    if alone is not None:
        return _plain(
            _lookup(alone[1], alone[2], sources=sources, defaults=defaults, path=path)
        )

    filled = PLACEHOLDER.sub(
        lambda match: str(
            _lookup(match[1], match[2], sources=sources, defaults=defaults, path=path)
        ),
        text,
    )
    if "{" in filled:
        raise UnfilledTemplate(path=path, placeholder=filled)
    return filled


def _lookup(
    prefix: str,
    name: str,
    *,
    sources: Mapping[str, object],
    defaults: Mapping[str, Any],
    path: str,
) -> Any:
    """The value behind one placeholder, or an exception naming it."""
    source = sources.get(prefix)
    if source is None:
        raise CatalogError(
            f"unknown placeholder source {{{prefix}.{name}}}", source=path
        )

    value = getattr(source, name, _MISSING)
    if value is _MISSING:
        raise CatalogError(f"{prefix} has no {name!r}", source=path)

    if _is_blank(value):
        value = defaults.get(name)
    if _is_blank(value):
        raise UnfilledTemplate(path=path, placeholder=f"{prefix}.{name}")
    return value


def _is_blank(value: Any) -> bool:
    """Unanswered, in the two shapes an unanswered field arrives in."""
    return value is None or value == ""


def _plain(value: Any) -> Any:
    """Tuples become lists: the spec is on its way into JSON."""
    if isinstance(value, tuple):
        return list(value)
    return value


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


_MISSING = object()
