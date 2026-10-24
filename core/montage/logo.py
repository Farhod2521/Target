"""What is known about a logo: what Claude saw once, and which copy goes where.

**Claude's look** (:class:`LogoAnalysis`) is asked for once per logo file
and prompt version, and stored. Montages never send the picture again;
they read what was stored.

**Copies.** A logo is drawn over video that may be dark or light. When a
sixth or more of a logo with transparency disappears on one of them, that
background gets a copy of its own. A logo in one colour is painted in the
other - white on dark, near-black on light: nothing of it is lost. A logo
in several colours keeps them, on a rounded plate of the opposite
lightness (a *badge*): painting a pink circle and purple lettering white
would keep the shape and lose the brand. A logo without transparency
carries its own background and is used as it is everywhere.
"""

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
# What a logo stood on: transparency of its own, a plain white or black
# ground taken away here, or a ground that stays - a coloured tile is
# part of the design, and a busy one cannot be cut out safely.
Ground = Literal["clear", "removed", "solid"]
HexColor = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]

MAX_NOTE_WORDS: Final = 30
# Thirty words of English, generously.
MAX_NOTE_CHARS: Final = 300
# A ground this light or this dark, and this grey, is paper.
PAPER_LIGHT: Final = 225
PAPER_DARK: Final = 30
GREY_SPREAD: Final = 18
# This much of a logo unseen on a background, and it gets one colour there.
# Low because lettering is thin: a wordmark beside a big mark is a fifth
# of the drawing and all of the name.
VANISHING: Final = 0.15
# One colour covering this much of the drawing is a one-colour logo; the
# rest is the soft edge of its strokes.
MONOCHROME: Final = 0.85
MAX_KEYWORDS: Final = 6
MAX_COLORS: Final = 5
# The silhouettes' colours, matching what text is drawn in.
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


# Every way the Uzbek o' and g' are typed, and the other marks a name is
# spelled with (okina, apostrophes, curly quotes, backtick). Dropped before
# comparing, so every spelling of "O'zbek" and "OZBEK" read the same.
_MARKS: Final = re.compile(r"['`\u02bb\u02bc\u2018\u2019\u00b4]")
_NOT_A_LETTER: Final = re.compile(r"[\W_]+")


def names_the_brand(*, text_in_logo: str, brand_name: str) -> bool:
    """Whether the logo's lettering spells the whole brand name.

    Read from the words, not from Claude's ``contains_brand_name``: a logo
    reading "CHILONZOR" beside the brand "Chilonzor Fitnes" was judged to
    contain it, and the name next to it would then have gone unwritten.
    Case, punctuation and the spellings of o' and g' are ignored; spacing
    is ignored inside the name ("BAHORKAFESI"), but the name must start
    and end on a word of the logo's - "Bahor" is not in "BAHORGUL".
    """
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
    """Which copy of the logo each background gets.

    ``shares`` are the logo's colours and how much of the drawing each
    covers. When :data:`VANISHING` of the drawing would vanish on a
    background - dark lettering beside a bright mark, say - that background
    gets a copy: the logo painted in one colour if it is one colour
    already (:data:`MONOCHROME`), else the logo as it is on a badge.
    """
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
