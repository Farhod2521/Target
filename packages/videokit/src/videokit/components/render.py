"""A component, its props and a brand, made into one Shotstack ``html5`` clip.

**Templates.** ``{{ name }}`` is a value, always escaped; ``{{{ name }}}``
is the drawing of an icon prop (:mod:`videokit.icons`),
``{{{ icon:star }}}`` that icon itself, and ``{{{ use:star }}}`` the same
drawn once per clip and repeated by reference - for an icon drawn many
times that no timeline reaches inside - the only markup a template is
given. A list repeats
what lies between ``{{#name}}`` and ``{{/name}}``, with ``{{ . }}`` for each
item; the same pair around a plain value keeps what is between only when
the value is not empty. Nothing else - no logic in templates.

Every template sees the component's props and the brand's fields
(``brand_name``, ``name_shown`` - empty when the logo already spells the
name - ``brand_tagline``, ``brand_initial``, ``logo``, the logo's copy for
the brand's own colour ``logo_on_primary``, and for dark and light footage
``logo_on_dark`` and ``logo_on_light``; ``cta_label``, ``cta_text`` and
``cta_contacts``, and ``cta_contact_lines`` - the same laid out on one
or more lines, see :mod:`videokit.components.lettering`). The timeline
sees the shared motion (``M`` and its helpers, see
:mod:`videokit.motion_tokens`), the props and the clip's own length as
``P`` - ``P.length`` is how
a component knows when to leave - and ``P.beats``: when each of its beats
lands (see ``beats`` in the registry), in seconds from the clip's start,
a list for a beat that is one per item. A beat nobody gave is missing,
and the timeline falls back to its own spacing.

**Sizes.** Every text is drawn at the size it was measured to fit its
box at (:mod:`videokit.components.lettering`), never cut off.

**Style.** The brand's font preset is inlined into each clip that writes
words, cut to the letters that clip writes - its text, its props (the
timeline may write them) and the manifest's ``glyphs`` (what a timeline
writes of its own, a counter's digits) - see :mod:`videokit.typefaces`.
Every colour is the brand's, as CSS variables: ``--primary``,
``--primary-deep`` (the primary darkened, for the far side of a
gradient and for dark plates), ``--accent``, ``--ink``, ``--on-primary``,
``--on-accent`` and ``--on-deep`` (text that reads on each - the
brand's own text colour when it does, else black or white). The canvas
is exactly the zone the clip sits in, so a component draws in that
zone's pixels. At a resolution other than 1080 the whole page is zoomed.
"""

import json
import re
from html import escape, unescape
from typing import Any, Final

from videokit.colors import TEXT_CONTRAST, contrast_ratio, readable_on, shade
from videokit.components.lettering import lettering
from videokit.components.logos import logo_css
from videokit.components.registry import Component, ComponentError
from videokit.icons import icon_svg
from videokit.layout import scaled, zone_box
from videokit.logo_fit import CARD_MAX, drawn_size, name_bar_logo, reads_at
from videokit.models import CONTACT_JOIN, AspectRatio, Brand, Resolution, Zone
from videokit.motion_tokens import prelude
from videokit.typefaces import FAMILY, font_css

_SECTION: Final = re.compile(r"\{\{#\s*(\w+)\s*\}\}(.*?)\{\{/\s*\1\s*\}\}", re.DOTALL)
_VALUE: Final = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_DRAWING: Final = re.compile(r"\{\{\{\s*(icon:|use:)?(\w+)\s*\}\}\}")
_SVG_BODY: Final = re.compile(r"^<svg[^>]*>(.*)</svg>$", re.DOTALL)
_ITEM: Final = re.compile(r"\{\{\s*\.\s*\}\}")
_TAG: Final = re.compile(r"<[^>]*>")
# How much of the primary is left in its deep shade.
DEEP_SHARE: Final = 0.35
# A beat lands no sooner than this into its clip (the entrance is under
# way) and no later than this before it leaves (the exit has begun).
BEAT_FIRST: Final = 0.05
BEAT_LAST: Final = 0.35
_BASE: Final = (
    "html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;"
    "background:transparent}"
    f"*{{box-sizing:border-box;font-family:'{FAMILY}',system-ui,sans-serif}}"
)


def component_clip(
    item: Component,
    *,
    props: dict[str, Any],
    brand: Brand,
    zone: Zone,
    start: float,
    length: float,
    resolution: Resolution,
    aspect_ratio: AspectRatio,
    top: int | None = None,
    marks: dict[str, str] | None = None,
    beats: dict[str, float | list[float]] | None = None,
) -> dict[str, Any]:
    """The clip that draws ``item`` over ``zone`` from ``start`` for
    ``length``; with ``top``, over the zone's band moved to start there.
    ``marks`` are values the code sets, never a planner: ``scrim``.
    ``beats`` are by the finished video's clock."""
    if zone not in item.zones:
        raise ComponentError(f"{item.name} may not sit in {zone}")
    values = item.cased(
        item.props_model().model_validate(props).model_dump(exclude_none=True)
    )
    shown = {**brand_values(brand), **values, **(marks or {})}
    sized = lettering(item, shown, brand=brand)
    icons = {p.name for p in item.props if p.kind == "icon"}
    html = fill(
        item.html,
        {**shown, **sized.values},
        drawings={n: icon_svg(values[n]) for n in icons if n in values},
    )
    words = {n: v for n, v in values.items() if n not in icons}
    letters = written(html) + _said(words) + item.glyphs
    return {
        "asset": {
            "type": "html5",
            "html": html,
            "css": (font_css(brand.font, letters=letters) if item.lettering else "")
            + _BASE
            + _variables(brand, resolution)
            + item.css
            + sized.css(item)
            + logo_css(item.name, {**shown, **values}),
            "js": _script(
                item.js,
                {**values, **(marks or {})},
                length=length,
                beats=relative(
                    item.beats_at(start, beats or {}), start=start, length=length
                ),
            ),
        },
        "start": round(start, 3),
        "length": round(length, 3),
        **zone_box(zone, resolution, aspect_ratio, top=top),
    }


def fill(
    template: str, values: dict[str, Any], *, drawings: dict[str, str] | None = None
) -> str:
    """The template with its values in, every one of them escaped, and
    its icons drawn."""
    drawn = drawings or {}
    shared: list[str] = []

    def drawing(match: re.Match[str]) -> str:
        kind, name = match.group(1), match.group(2)
        if kind == "icon:":
            return icon_svg(name)  # type: ignore[arg-type]
        if kind == "use:":
            if name not in shared:
                shared.append(name)
            return (
                '<svg viewBox="0 0 24 24" width="100%" height="100%">'
                f'<use href="#i-{name}"/></svg>'
            )
        return drawn.get(name, "")

    template = _DRAWING.sub(drawing, template) + "".join(
        f'<svg width="0" height="0" style="position:absolute"><symbol id="i-{n}" '
        f'viewBox="0 0 24 24">{_svg_body(n)}</symbol></svg>'
        for n in shared
    )

    def section(match: re.Match[str]) -> str:
        value, body = values.get(match.group(1)), match.group(2)
        if isinstance(value, list):
            items = (escape(str(item)) for item in value)
            return "".join(_ITEM.sub(_literal(item), body) for item in items)
        return body if value else ""

    def value(match: re.Match[str]) -> str:
        return escape(str(values.get(match.group(1), "")))

    # A section inside another comes out on the next pass.
    while (inner := _SECTION.sub(section, template)) != template:
        template = inner
    return _VALUE.sub(value, template)


def _svg_body(name: str) -> str:
    found = _SVG_BODY.match(icon_svg(name))  # type: ignore[arg-type]
    return found.group(1) if found else ""


def written(html: str) -> str:
    """The words a filled template shows, markup left out."""
    return unescape(_TAG.sub(" ", html))


def _said(values: dict[str, Any]) -> str:
    """Every text among the props, which a timeline may write itself."""
    return " ".join(
        " ".join(map(str, v)) if isinstance(v, list) else str(v)
        for v in values.values()
    )


def _literal(text: str) -> Any:
    """A replacement ``re.sub`` takes as it is, backslashes and all."""
    return lambda _match: text


def brand_values(brand: Brand) -> dict[str, Any]:
    """What every template sees of the brand - see the module's docstring.

    The logo stands for the name only where its lettering reads at the
    size that place allows (:mod:`videokit.logo_fit`); elsewhere the name
    is written out beside or under it.
    """
    on_primary = brand.logo_on(brand.primary)
    spelled = brand.name_in_logo and bool(brand.logo)
    bar_named = not (spelled and name_bar_logo(on_primary))
    card_named = not spelled
    if spelled:
        size = drawn_size(on_primary, CARD_MAX)
        card_named = size is None or not reads_at(on_primary, size[1])
    initial = (brand.name[:1] or "\u2022").upper()
    contacts = [part for part in brand.cta_contacts.split(CONTACT_JOIN) if part]
    button = brand.cta_text or (contacts[0] if contacts else "")
    return {
        "brand_name": brand.name,
        "name_shown": brand.name if bar_named else "",
        "card_name": brand.name if card_named else "",
        "brand_tagline": brand.tagline,
        "brand_initial": initial,
        "logo": brand.logo,
        "logo_on_primary": on_primary,
        "card_logo": on_primary if brand.logo else "",
        # A name bar's three ways to start: the logo instead of the name
        # it spells, the logo beside the name, or the name's first letter.
        "logo_instead_of_name": "" if bar_named else on_primary,
        "logo_beside_name": on_primary if bar_named else "",
        "initial_without_logo": "" if brand.logo else initial,
        "logo_on_dark": brand.logo_on_dark or brand.logo,
        "logo_on_light": brand.logo_on_light or brand.logo,
        "cta_label": brand.cta_label,
        "cta_text": brand.cta_text,
        "cta_contacts": brand.cta_contacts,
        # The closing button: what to do, and every way to do it below.
        "cta_button_text": button,
        "end_contact_lines": contacts if brand.cta_text else contacts[1:],
    }


def _variables(brand: Brand, resolution: Resolution) -> str:
    zoom = scaled(1000, resolution) / 1000
    page = f"body{{zoom:{zoom:g}}}" if zoom != 1 else ""
    deep = shade(brand.primary, share=DEEP_SHARE)
    return (
        f":root{{--primary:{brand.primary};--accent:{brand.accent};"
        f"--primary-deep:{deep};"
        f"--ink:{brand.text};--on-primary:{_text_on(brand.primary, brand)};"
        f"--on-accent:{_text_on(brand.accent, brand)};"
        f"--on-deep:{_text_on(deep, brand)}}}{page}"
    )


def _text_on(background: str, brand: Brand) -> str:
    """The brand's text colour where it reads on ``background``, else
    black or white, whichever does."""
    if contrast_ratio(brand.text, background) >= TEXT_CONTRAST:
        return brand.text
    return readable_on(background)


def relative(
    beats: dict[str, float | list[float]], *, start: float, length: float
) -> dict[str, float | list[float]]:
    """Beats by the clip's own clock, each kept inside it: a beat the clip
    starts after lands at once, one past its exit just before it."""

    def inside(at: float) -> float:
        return round(min(max(at - start, BEAT_FIRST), max(length - BEAT_LAST, 0)), 3)

    return {
        name: [inside(at) for at in value] if isinstance(value, list) else inside(value)
        for name, value in beats.items()
    }


def _script(
    js: str,
    values: dict[str, Any],
    *,
    length: float,
    beats: dict[str, float | list[float]],
) -> str:
    data = json.dumps(
        {**values, "length": round(length, 3), "beats": beats}, ensure_ascii=False
    )
    # A prop that says "</script>" must stay a string.
    return f"const P={data.replace('</', '<\\/')};{prelude(js)}{js}"
