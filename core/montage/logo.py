"""What is known about a logo: what Claude saw once, and which copy goes where."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from videokit.typefaces import FontPreset

from core.montage.colors import DARK, LIGHT, SHAPE_CONTRAST, contrast_ratio

LogoType = Literal["wordmark", "icon", "combination"]
Background = Literal["dark", "light", "any"]
Treatment = Literal["own", "white", "black", "light_badge", "dark_badge"]
Ground = Literal["clear", "removed", "solid"]
HexColor = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]

MAX_NOTE_WORDS: Final = 30
MAX_NOTE_CHARS: Final = 300
PAPER_LIGHT: Final = 225
PAPER_DARK: Final = 30
GREY_SPREAD: Final = 18
VANISHING: Final = 0.15
MONOCHROME: Final = 0.85
MAX_KEYWORDS: Final = 6
MAX_COLORS: Final = 5
WHITE: Final = LIGHT
BLACK: Final = DARK


class LogoAnalysis(BaseModel):
    """Claude's description of one logo."""

    model_config = ConfigDict(frozen=True)

    logo_type: LogoType = Field(
        description="wordmark = only letters; icon = only a symbol; "
        "combination = a symbol and letters together."
    )
    text_in_logo: str = Field(
        max_length=80,
        description="The words written in the logo exactly as spelled, "
        "or an empty string if there are none.",
    )
    contains_brand_name: bool = Field(
        description="True if the brand name given is legible in the logo."
    )
    dominant_colors: list[HexColor] = Field(
        max_length=MAX_COLORS, description="The logo's main colours, commonest first."
    )
    best_background: Background = Field(
        description="The background the logo reads best on."
    )
    style_keywords: list[str] = Field(
        max_length=MAX_KEYWORDS,
        description="Up to six single English words for its style.",
    )
    suggested_font_preset: FontPreset = Field(
        description="The font preset that suits the logo best."
    )
    suggested_accent: HexColor = Field(
        description="A colour for highlights that suits the logo and stands out "
        "on video."
    )
    notes: str = Field(
        max_length=MAX_NOTE_CHARS,
        description=f"At most {MAX_NOTE_WORDS} words: one or two complete "
        "sentences on anything a video editor should know.",
    )

    @field_validator("notes")
    @classmethod
    def _short(cls, value: str) -> str:
        """Refused rather than cut: a note cut at its thirtieth word stops
        mid-sentence. The refusal goes back to Claude, which writes it
        again shorter."""
        words = value.split()
        if len(words) > MAX_NOTE_WORDS:
            raise ValueError(
                f"notes must be at most {MAX_NOTE_WORDS} words, not {len(words)}"
            )
        return " ".join(words)


_MARKS: Final = re.compile(r"['`\u02bb\u02bc\u2018\u2019\u00b4]")
_NOT_A_LETTER: Final = re.compile(r"[\W_]+")


def names_the_brand(*, text_in_logo: str, brand_name: str) -> bool:
    """Whether the logo's lettering spells the whole brand name."""
    name = _words(brand_name)
    lettering = _words(text_in_logo)
    if not name or not lettering:
        return False
    whole = "".join(name)
    return any(
        "".join(lettering[start:end]) == whole
        for start in range(len(lettering))
        for end in range(start + 1, len(lettering) + 1)
    )


def _words(text: str) -> list[str]:
    plain = _MARKS.sub("", unicodedata.normalize("NFKC", text).casefold())
    return _NOT_A_LETTER.sub(" ", plain).split()


def removable(background: str) -> bool:
    """Whether a plain ground is paper rather than design: near white or
    near black, with no colour of its own."""
    red, green, blue = (int(background[i : i + 2], 16) for i in (1, 3, 5))
    high, low = max(red, green, blue), min(red, green, blue)
    return high - low <= GREY_SPREAD and (low >= PAPER_LIGHT or high <= PAPER_DARK)


@dataclass(frozen=True, slots=True)
class Copies:
    """How the logo is drawn on each kind of background."""

    on_dark: Treatment
    on_light: Treatment


def copies(*, has_alpha: bool, shares: Sequence[tuple[str, float]]) -> Copies:
    """Which copy of the logo each background gets."""
    if not has_alpha or not shares:
        return Copies(on_dark="own", on_light="own")
    single = shares[0][1] >= MONOCHROME
    on_dark: Treatment = "own"
    if _vanishing(shares, DARK) >= VANISHING:
        on_dark = "white" if single else "light_badge"
    on_light: Treatment = "own"
    if _vanishing(shares, LIGHT) >= VANISHING:
        on_light = "black" if single else "dark_badge"
    return Copies(on_dark=on_dark, on_light=on_light)


def _vanishing(shares: Sequence[tuple[str, float]], background: str) -> float:
    return sum(
        share
        for colour, share in shares
        if contrast_ratio(colour, background) < SHAPE_CONTRAST
    )
