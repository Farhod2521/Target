"""Every component this package can draw, read from its own folder.

A component is a folder under ``videokit/components/`` holding four files:

- ``manifest.json`` - its name, one or two sentences a planner reads, the
  props it takes (texts and lists with length limits, and icons - one of
  :data:`videokit.icons.ICONS` - of type ``icon``), the zones it may sit in, how long
  it may stay, its sound (one of :mod:`videokit.sounds`), whether it
  needs a layout, which of the brand's values it is there to show
  (``shows_brand`` - with none of them it is not drawn at all), example
  props, where its content sits in its zone (``box``: left, top, right,
  bottom in design pixels) and the box each text is written in
  (``texts``: size, smallest size, width and lines - see
  :mod:`videokit.fit`) and any letters its timeline writes on its own
  (``glyphs``: a counter's digits), which the clip's font must keep, and
  its beats (``beats``: name - what happens - for each moment inside it
  that lands on a word: a stamp hitting, a list's item checked; a beat
  named after a list prop is one moment per item);
- ``template.html``, ``style.css``, ``timeline.js`` - what is drawn and
  how it moves.

A new folder is a new component: nothing else lists them. The rules every
component keeps are checked here, when the folder is read, so a component
that breaks one never reaches a render:

- motion only through the GSAP timeline the renderer seeks - no timers,
  no animation frames, no clock;
- nothing fetched - no remote script, style, image or font;
- no canvas, which the renderer cannot seek;
- sizes in pixels, never relative to a font or a window;
- no capitals by CSS (``text-transform``): a clip's font keeps only the
  letters it writes, so a prop meant in capitals is listed in ``caps``
  and written so before it is drawn.
"""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from videokit.components.rules import ComponentError, check
from videokit.fit import TextBox
from videokit.icons import IconName
from videokit.layout import PLACEABLE
from videokit.models import Brand, Layout, Zone
from videokit.sounds import sounds

FOLDER: Final = Path(__file__).parent

# Who places a component: the planner, or the code on its own (an end card
# is never left to a planner's choice).
Placement = Literal["planner", "auto"]
# A backdrop fills the frame under the other components and does not
# compete with them for a zone; a decoration (a sticker flying past) is
# drawn under the front ones, never shares a moment with one in its band,
# and is not counted when bands are checked for clashes.
Layer = Literal["front", "decor", "backdrop"]

# Brand values a component can be there to show (``shows_brand``).
BRAND_VALUES: Final = frozenset({"name", "logo", "tagline", "cta_label"})


@dataclass(frozen=True, slots=True)
class PropSpec:
    """One field a planner fills in."""

    name: str
    kind: Literal["text", "list", "icon"]
    description: str
    required: bool
    min_length: int = 1
    max_length: int = 60
    min_items: int = 1
    max_items: int = 5


@dataclass(frozen=True, slots=True)
class Component:
    """One component, as read from its folder."""

    name: str
    description: str
    props: tuple[PropSpec, ...]
    zones: tuple[Zone, ...]
    min_seconds: float
    max_seconds: float
    sfx: str
    layout: Layout | None
    placement: Placement
    layer: Layer
    html: str
    css: str
    js: str
    # Props to show it with when nobody gave any: demos and tests.
    example: dict[str, Any]
    shows_brand: tuple[str, ...] = ()
    # Whether it writes any words. One that does not is drawn without the
    # brand's font - a font inlined into a picture is weight for nothing.
    lettering: bool = True
    # Where its content sits in its zone, and each text's box, by the
    # name of the value it shows (a prop or a brand value).
    box: tuple[int, int, int, int] | None = None
    texts: tuple[tuple[str, TextBox], ...] = ()
    # A tap circle on the button's edge: its radius, and how far in from
    # that edge the button's words start.
    tap: tuple[int, int] | None = None
    # Letters its timeline writes that no prop or template holds: a
    # counter's digits. Kept in the clip's cut of the font.
    glyphs: str = ""
    # Props drawn in capitals, written so before the template is filled.
    caps: tuple[str, ...] = ()
    # Moments inside it that land on words, each with what happens then.
    beats: tuple[tuple[str, str], ...] = ()
    # A sound for each beat that has one (``start``: as it comes in), and
    # where a beat lands when the planner gave no word for it, in seconds
    # from the start - so the sound and the motion always meet.
    sounds: tuple[tuple[str, str], ...] = ()
    beat_defaults: tuple[tuple[str, float], ...] = ()
    # An opening headline: one of these is on screen from the first frame.
    hook: bool = False
    # How many times one video may show it; None: no limit.
    max_uses: int | None = None

    def beats_at(
        self, start: float, given: dict[str, float | list[float]]
    ) -> dict[str, float | list[float]]:
        """Its beats by the finished video's clock: the ones given, and the
        manifest's own moment for each that was not."""
        return {**{n: start + at for n, at in self.beat_defaults}, **given}

    def beat_is_list(self, name: str) -> bool:
        """Whether a beat is one moment per item of the list prop it names."""
        return any(p.name == name and p.kind == "list" for p in self.props)

    def drawable(self, brand: Brand) -> bool:
        """Whether the brand has anything this component is there to show.

        A name bar with no name would be an empty box; it is left out.
        """
        return not self.shows_brand or any(
            getattr(brand, value) for value in self.shows_brand
        )

    def cased(self, values: dict[str, Any]) -> dict[str, Any]:
        """``values`` with the props drawn in capitals written so."""
        return {
            name: _upper(value) if name in self.caps else value
            for name, value in values.items()
        }

    def props_model(self) -> type[BaseModel]:
        """A pydantic model of the props, limits included."""
        fields: dict[str, Any] = {spec.name: _field(spec) for spec in self.props}
        return create_model(
            f"{_camel(self.name)}Props",
            __config__=ConfigDict(extra="forbid"),
            **fields,
        )


def _upper(value: Any) -> Any:
    if isinstance(value, list):
        return [str(item).upper() for item in value]
    return str(value).upper() if isinstance(value, str) else value


def _field(spec: PropSpec) -> tuple[Any, Any]:
    """One prop as a pydantic ``(annotation, field)`` pair."""
    text: Any = Annotated[
        str, Field(min_length=spec.min_length, max_length=spec.max_length)
    ]
    if spec.kind == "icon":
        annotation, low, high = IconName, None, None
    elif spec.kind == "text":
        annotation, low, high = text, None, None
    else:
        annotation, low, high = list[text], spec.min_items, spec.max_items  # type: ignore[valid-type]
    if not spec.required:
        annotation = annotation | None
    default: Any = ... if spec.required else None
    field = Field(
        default, description=spec.description, min_length=low, max_length=high
    )
    return annotation, field


def _camel(name: str) -> str:
    return "".join(part.title() for part in name.split("_"))


@cache
def components() -> dict[str, Component]:
    """Every component, by name, in name order."""
    found = {}
    for folder in sorted(
        p for p in FOLDER.iterdir() if (p / "manifest.json").is_file()
    ):
        component = _read(folder)
        found[component.name] = component
    return found


def component(name: str) -> Component:
    """One component by name; ``ComponentError`` when there is none."""
    try:
        return components()[name]
    except KeyError as exc:
        raise ComponentError(f"no component named {name!r}") from exc


def _read(folder: Path) -> Component:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("name") != folder.name:
        raise ComponentError(f"{folder.name}: manifest names {manifest.get('name')!r}")
    html, css, js = (
        (folder / name).read_text(encoding="utf-8")
        for name in ("template.html", "style.css", "timeline.js")
    )
    # Every byte of a clip counts against the provider's limit on an edit.
    css = " ".join(line.strip() for line in css.splitlines() if line.strip())
    js = "\n".join(line.strip() for line in js.splitlines() if line.strip())
    check(folder.name, html=html, css=css, js=js)
    zones = tuple(manifest["zones"])
    if not zones or not set(zones) <= PLACEABLE:
        raise ComponentError(f"{folder.name}: zones {zones} are not all placeable")
    low, high = float(manifest["min_seconds"]), float(manifest["max_seconds"])
    if not 0 < low <= high:
        raise ComponentError(f"{folder.name}: seconds {low}-{high}")
    shows = tuple(manifest.get("shows_brand", []))
    if not set(shows) <= BRAND_VALUES:
        raise ComponentError(f"{folder.name}: shows_brand {shows} is not all known")
    sfx = manifest.get("sfx", "")
    named = [sfx, *manifest.get("sounds", {}).values()]
    if missing := [n for n in named if n and n not in sounds()]:
        raise ComponentError(f"{folder.name}: no sound named {missing}")
    required = set(manifest.get("required", []))
    plain = {n for n, raw in manifest["props"].items() if raw["type"] == "string"}
    if clash := plain & set(manifest.get("beats", {})):
        raise ComponentError(f"{folder.name}: beats {clash} name a text prop")
    return Component(
        name=folder.name,
        description=" ".join(manifest["description"].split()),
        props=tuple(
            _prop(n, raw, n in required) for n, raw in manifest["props"].items()
        ),
        zones=zones,
        min_seconds=low,
        max_seconds=high,
        sfx=sfx,
        layout=manifest.get("layout"),
        placement=manifest.get("placement", "planner"),
        layer=manifest.get("layer", "front"),
        html=html,
        css=css,
        js=js,
        example=manifest.get("example", {}),
        shows_brand=shows,
        lettering=bool(manifest.get("lettering", True)),
        box=tuple(manifest["box"]) if "box" in manifest else None,
        texts=tuple(
            (value, TextBox(**raw)) for value, raw in manifest.get("texts", {}).items()
        ),
        tap=(manifest["tap"]["radius"], manifest["tap"]["text_inset"])
        if "tap" in manifest
        else None,
        glyphs=str(manifest.get("glyphs", "")),
        caps=tuple(manifest.get("caps", [])),
        beats=tuple((str(k), str(v)) for k, v in manifest.get("beats", {}).items()),
        sounds=tuple((str(k), str(v)) for k, v in manifest.get("sounds", {}).items()),
        beat_defaults=tuple(
            (str(k), float(v)) for k, v in manifest.get("beat_defaults", {}).items()
        ),
        hook=bool(manifest.get("hook", False)),
        max_uses=manifest.get("max_uses"),
    )


def _prop(name: str, raw: dict[str, Any], required: bool) -> PropSpec:
    if raw["type"] == "icon":
        return PropSpec(
            name=name,
            kind="icon",
            description=raw.get("description", ""),
            required=required,
        )
    if raw["type"] == "string":
        return PropSpec(
            name=name,
            kind="text",
            description=raw.get("description", ""),
            required=required,
            min_length=raw.get("minLength", 1),
            max_length=raw["maxLength"],
        )
    item = raw["items"]
    return PropSpec(
        name=name,
        kind="list",
        description=raw.get("description", ""),
        required=required,
        min_length=item.get("minLength", 1),
        max_length=item["maxLength"],
        min_items=raw.get("minItems", 1),
        max_items=raw["maxItems"],
    )
