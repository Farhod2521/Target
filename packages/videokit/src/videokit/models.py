"""What goes into a montage and what comes back from the provider.

Times are seconds as floats: they are positions in a media file, measured
by FFprobe and spoken by Shotstack in the same unit, and nothing here is
money.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from videokit.colors import is_dark
from videokit.typefaces import DEFAULT_FONT, FontPreset

Environment = Literal["stage", "v1"]
AspectRatio = Literal["9:16", "1:1", "16:9", "4:5"]
Resolution = Literal["sd", "hd", "1080"]
TextPosition = Literal["top", "center", "bottom"]
# Named bands of the frame and the two ways footage fills it; the pixels
# behind both live in :mod:`videokit.layout`.
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
# How a cut comes in. ``none`` is a plain cut; the rest mark a new part of
# the video (see :mod:`videokit.motion`); ``burst`` is the flash and the
# landing zoom at once, with a whoosh.
Transition = Literal["none", "fade", "slide", "zoom", "flash", "burst"]
# ``still`` keeps the footage as cut; ``moving`` adds the slow push-in,
# punch-ins, transitions and sound of :mod:`videokit.motion` and
# :mod:`videokit.audio`.
Motion = Literal["still", "moving"]
# What happens to the sound while a file is prepared: ``none`` for a file
# with no sound, ``level`` evens out the loudness only, ``voice`` also
# strips the hum and hiss under speech before levelling.
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
# Between a handle and a phone number on one line.
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
    # A small logo in the corner all through the video.
    show_corner_logo: bool = False
    # Whether the logo's own lettering already spells ``name``: a name bar
    # beside it then shows the logo without writing the name again.
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
    # Where the line is drawn, when it was moved off the speaker's face:
    # its band's top and bottom in design pixels, and its size. None: the
    # subtitles' own band, at the size every line fits at.
    top: int | None = None
    bottom: int | None = None
    px: int | None = None
    # How light the footage behind the line is (0-1, its lighter part),
    # and whether a dark backing is drawn under it because that is too
    # light for the words.
    backdrop: float | None = None
    scrim: bool = False


class ComponentUse(_Frozen):
    """One component on screen: which, where, when, and with what words."""

    name: str
    zone: Zone
    start: float = Field(ge=0)
    length: float = Field(gt=0)
    props: dict[str, Any] = Field(default_factory=dict)
    # The zone's band moved to start here (design pixels), off the
    # speaker's face; None: where the zone is.
    top: int | None = None
    # Words over the footage: how light the footage behind them is, and
    # whether a soft dark backing is drawn under them.
    backdrop: float | None = None
    scrim: bool = False
    # When each of its beats lands (see the component's manifest), by the
    # finished video's clock: one moment, or one per item of a list.
    # ``shows`` is the code's own: start and end of each stretch a long
    # clip is actually seen in, one after another.
    beats: dict[str, float | list[float]] = Field(default_factory=dict)

    def windows(self) -> list[tuple[float, float]]:
        """The stretches it is seen in: all of it, or its ``shows``."""
        shows = self.beats.get("shows")
        if isinstance(shows, list) and len(shows) >= 2:
            return list(zip(shows[0::2], shows[1::2], strict=False))
        return [(self.start, self.start + self.length)]


# Left, top, right, bottom.
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
    # How far a split moves the footage down, as a share of the frame's
    # height; None: the usual distance.
    shift: float | None = None


class EditSpec(_Frozen):
    """Everything one render needs, in this package's own words."""

    source_url: str
    cuts: tuple[Cut, ...] = Field(min_length=1)
    aspect_ratio: AspectRatio = "9:16"
    resolution: Resolution = "hd"
    # Subtitles word by word; when empty, ``captions_url`` (an SRT file)
    # is the fallback that only knows when each line starts and ends.
    captions: tuple[CaptionLine, ...] = ()
    captions_url: str = ""
    overlays: tuple[Overlay, ...] = ()
    # Graphics over the footage, and where the footage moves aside for
    # them. Times are the finished video's.
    components: tuple[ComponentUse, ...] = ()
    layouts: tuple[LayoutSpan, ...] = ()
    brand: Brand = Field(default_factory=Brand)
    motion: Motion = "still"
    # Moments of the finished video to punch in on, and where each short
    # sound is (by name, see :mod:`videokit.sounds`); a sound with no
    # address is left out.
    punches: tuple[float, ...] = ()
    sound_urls: dict[str, str] = Field(default_factory=dict)
    # The speaker's face through the video (see :mod:`videokit.faces`),
    # for the checks before a render.
    faces: tuple[FaceMark, ...] = ()
    music_url: str = ""
    music_volume: float = Field(default=0.2, ge=0, le=1)
    # Seconds the video runs on after its last cut, under the closing
    # card: the source carries on from ``tail_from``, silent.
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
    # When the provider took the file and when it last changed state: once
    # ``ready``, the two apart are how long the copy-in took.
    created: datetime | None = None
    updated: datetime | None = None


class RenderState(_Frozen):
    """How far one render got, and the finished file when it is there."""

    id: str
    status: RenderStatus
    url: str = ""
    error: str = ""
    # What the provider bills by and how long it worked, once ``done``.
    duration: float | None = None
    render_ms: int | None = None
    # From the request to the finished file: queue, fetching and saving
    # as well as the render itself.
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
