"""Every component this package can draw, read from its own folder."""

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

Placement = Literal["planner", "auto"]
Layer = Literal["front", "decor", "backdrop"]

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
    example: dict[str, Any]
    shows_brand: tuple[str, ...] = ()
    lettering: bool = True
    box: tuple[int, int, int, int] | None = None
    texts: tuple[tuple[str, TextBox], ...] = ()
    tap: tuple[int, int] | None = None
    glyphs: str = ""
    caps: tuple[str, ...] = ()
    beats: tuple[tuple[str, str], ...] = ()
    sounds: tuple[tuple[str, str], ...] = ()
    beat_defaults: tuple[tuple[str, float], ...] = ()
    hook: bool = False
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
        """Whether the brand has anything this component is there to show."""
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
