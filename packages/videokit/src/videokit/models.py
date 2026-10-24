"""What goes into a montage and what comes back from the provider."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from videokit.colors import is_dark
from videokit.typefaces import DEFAULT_FONT, FontPreset

Environment = Literal["stage", "v1"]
AspectRatio = Literal["9:16", "1:1", "16:9", "4:5"]
Resolution = Literal["sd", "hd", "1080"]
TextPosition = Literal["top", "center", "bottom"]
Zone = Literal[
    "SAFE_TOP",
    "CORNER",
    "TOP_TITLE",
    "TOP_PANEL",
    "CENTER",
    "LOWER_THIRD",
    "SUBTITLES",
    "SUBTITLES_LOW",
    "SAFE_BOTTOM",
    "EDGE",
    "FULL",
]
Layout = Literal["full", "split_top"]
Transition = Literal["none", "fade", "slide", "zoom", "flash", "burst"]
Motion = Literal["still", "moving"]
AudioTreatment = Literal["none", "level", "voice"]

SourceStatus = Literal["queued", "importing", "ready", "failed", "deleted"]
RenderStatus = Literal[
    "queued",
    "fetching",
    "preprocessing",
    "generating",
    "rendering",
    "saving",
    "done",
    "failed",
]
FINISHED: frozenset[str] = frozenset({"done", "failed"})


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Cut(_Frozen):
    """One stretch of the source kept, by its own clock.

    ``zoom`` above one pushes in on the picture for this stretch - an
    editor's way of hiding a jump between two takes of one shot. ``enter``
    is how it comes in after the one before it.
    """

    start: float = Field(ge=0)
    end: float = Field(gt=0)
    zoom: float = Field(default=1.0, ge=1.0, le=1.5)
    enter: Transition = "none"


class Overlay(_Frozen):
    """A line of text over the finished video, by the finished video's clock."""

    text: str = Field(min_length=1)
    start: float = Field(ge=0)
    length: float = Field(gt=0)
    position: TextPosition = "center"


HexColor = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
CONTACT_JOIN = " \u00b7 "


class Brand(_Frozen):
    """What makes a montage look like one business: colours, words, a logo.

    ``logo`` is a ``data:`` URI - the renderer may fetch nothing - and
    empty when there is none; the components then draw the name's first
    letter instead. ``logo_on_dark`` and ``logo_on_light`` are the copies
    made to be seen on each (one colour where the logo's own would vanish);
    see :meth:`logo_on`.
    """

    primary: HexColor = "#1f3a93"
    accent: HexColor = "#ffd400"
    text: HexColor = "#ffffff"
    name: str = Field(default="", max_length=60)
    tagline: str = Field(default="", max_length=80)
    cta_text: str = Field(default="", max_length=40)
    cta_handle: str = Field(default="", max_length=40)
    cta_phone: str = Field(default="", max_length=20)
    logo: str = ""
    logo_on_dark: str = ""
    logo_on_light: str = ""
    font: FontPreset = DEFAULT_FONT
    show_corner_logo: bool = False
    name_in_logo: bool = False

    @property
    def cta_contacts(self) -> str:
        """Every way to get in touch, together: ``@shop · +99890...``."""
        return CONTACT_JOIN.join(p for p in (self.cta_handle, self.cta_phone) if p)

    @property
    def cta_label(self) -> str:
        """The button's words: what to do, and every way to do it."""
        if self.cta_text and self.cta_contacts:
            return f"{self.cta_text}: {self.cta_contacts}"
        return self.cta_text or self.cta_contacts

    def logo_on(self, background: str) -> str:
        """The copy of the logo that reads on ``background``, a ``#rrggbb``."""
        made = self.logo_on_dark if is_dark(background) else self.logo_on_light
        return made or self.logo


class CaptionWord(_Frozen):
    """One spoken word, by the finished video's clock."""

    text: str = Field(min_length=1)
    start: float = Field(ge=0)
    end: float = Field(ge=0)


class CaptionLine(_Frozen):
    """One subtitle on screen, and each of its words as it is heard."""

    start: float = Field(ge=0)
    end: float = Field(gt=0)
    words: tuple[CaptionWord, ...] = Field(min_length=1)
    top: int | None = None
    bottom: int | None = None
    px: int | None = None
    backdrop: float | None = None
    scrim: bool = False


class ComponentUse(_Frozen):
    """One component on screen: which, where, when, and with what words."""

    name: str
    zone: Zone
    start: float = Field(ge=0)
    length: float = Field(gt=0)
    props: dict[str, Any] = Field(default_factory=dict)
    top: int | None = None
    backdrop: float | None = None
    scrim: bool = False
    beats: dict[str, float | list[float]] = Field(default_factory=dict)

    def windows(self) -> list[tuple[float, float]]:
        """The stretches it is seen in: all of it, or its ``shows``."""
        shows = self.beats.get("shows")
        if isinstance(shows, list) and len(shows) >= 2:
            return list(zip(shows[0::2], shows[1::2], strict=False))
        return [(self.start, self.start + self.length)]


Rect = tuple[float, float, float, float]


class FaceMark(_Frozen):
    """The speaker's face at one moment of the finished video, in design
    pixels, with the footage filling the frame (a split moves it down):
    its box, and the part never to cover - the eyes and the mouth."""

    at: float
    box: Rect
    guard: Rect


class LayoutSpan(_Frozen):
    """A stretch of the finished video with the footage laid out one way."""

    start: float = Field(ge=0)
    end: float = Field(gt=0)
    layout: Layout
    shift: float | None = None


class EditSpec(_Frozen):
    """Everything one render needs, in this package's own words."""

    source_url: str
    cuts: tuple[Cut, ...] = Field(min_length=1)
    aspect_ratio: AspectRatio = "9:16"
    resolution: Resolution = "hd"
    captions: tuple[CaptionLine, ...] = ()
    captions_url: str = ""
    overlays: tuple[Overlay, ...] = ()
    components: tuple[ComponentUse, ...] = ()
    layouts: tuple[LayoutSpan, ...] = ()
    brand: Brand = Field(default_factory=Brand)
    motion: Motion = "still"
    punches: tuple[float, ...] = ()
    sound_urls: dict[str, str] = Field(default_factory=dict)
    faces: tuple[FaceMark, ...] = ()
    music_url: str = ""
    music_volume: float = Field(default=0.2, ge=0, le=1)
    tail: float = Field(default=0.0, ge=0)
    tail_from: float = Field(default=0.0, ge=0)

    @property
    def length(self) -> float:
        """How long the finished video runs: the cuts end to end, then the
        tail."""
        return round(sum(cut.end - cut.start for cut in self.cuts) + self.tail, 3)


class Source(_Frozen):
    """A file the provider holds, and whether it is ready to edit."""

    id: str
    status: SourceStatus
    url: str = ""
    duration: float | None = None
    created: datetime | None = None
    updated: datetime | None = None


class RenderState(_Frozen):
    """How far one render got, and the finished file when it is there."""

    id: str
    status: RenderStatus
    url: str = ""
    error: str = ""
    duration: float | None = None
    render_ms: int | None = None
    total_ms: int | None = None
    created: datetime | None = None
    updated: datetime | None = None

    @property
    def finished(self) -> bool:
        return self.status in FINISHED


class MediaInfo(_Frozen):
    """What FFprobe says about a file."""

    duration: float = Field(ge=0)
    width: int = 0
    height: int = 0
    has_audio: bool = False


class Frame(_Frozen):
    """One still, at a moment in the source."""

    at: float = Field(ge=0)
    jpeg: bytes
