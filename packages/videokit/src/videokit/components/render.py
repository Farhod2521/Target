"""A component, its props and a brand, made into one Shotstack ``html5`` clip."""

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
DEEP_SHARE: Final = 0.35
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
    """What every template sees of the brand - see the module's docstring."""
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
        "logo_instead_of_name": "" if bar_named else on_primary,
        "logo_beside_name": on_primary if bar_named else "",
        "initial_without_logo": "" if brand.logo else initial,
        "logo_on_dark": brand.logo_on_dark or brand.logo,
        "logo_on_light": brand.logo_on_light or brand.logo,
        "cta_label": brand.cta_label,
        "cta_text": brand.cta_text,
        "cta_contacts": brand.cta_contacts,
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
    return f"const P={data.replace('</', '<\\/')};{prelude(js)}{js}"
