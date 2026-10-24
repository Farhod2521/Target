"""Filling ``{business.city}`` and ``{answers.age_min}`` in a preset.

A preset is data, so the only thing it can carry is a hole with a name on
it. The allowed names are a closed set and the caller passes exactly them:
an open set would make a YAML file able to reach into whatever the caller
happened to hand over, which is how data files quietly become code.

Three names. ``conversion`` is a source in its own right rather than a
field on ``business`` for a plain reason: it comes from the ad account,
not from the profile, and it is absent for most launches.

A placeholder standing alone becomes the value itself, keeping its type -
``age_min`` has to arrive as a number, not as ``"25"``. A placeholder
inside a sentence becomes text, because that is the only thing it can be.
"""

import re
from collections.abc import Mapping
from typing import Any

from core.targeting.exceptions import CatalogError, UnfilledTemplate

# ``{prefix.name}``. Lowercase on purpose: a mis-cased placeholder does not
# match, survives into the output, and is then caught by the leftover-brace
# check below with the file and path attached - which is a far better error
# than a silently unfilled field.
PLACEHOLDER = re.compile(r"\{([a-z_]+)\.([a-z_][a-z_0-9]*)\}")


def render(
    node: Any,
    *,
    sources: Mapping[str, object],
    defaults: Mapping[str, Any],
    path: str = "",
) -> Any:
    """Walk a preset fragment, replacing every placeholder it contains.

    ``defaults`` fills a hole whose source answered ``None`` or ``""``. It
    is keyed by the bare name, without the prefix, because a preset's
    ``defaults`` block answers the question "what if nobody said", and the
    answer does not depend on which object was going to be asked.
    """
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
    """Unanswered, in the two shapes an unanswered field arrives in.

    An empty tuple is not blank. ``genders = ()`` means "everyone", and
    replacing that with a preset default would overrule a real answer.
    """
    return value is None or value == ""


def _plain(value: Any) -> Any:
    """Tuples become lists: the spec is on its way into JSON."""
    if isinstance(value, tuple):
        return list(value)
    return value


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


# A sentinel, because ``None`` is a value a source may legitimately hold and
# "the attribute does not exist" is a different mistake with a different fix.
_MISSING = object()
